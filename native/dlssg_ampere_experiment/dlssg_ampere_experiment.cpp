// Copyright (c) 2026 DeepBeepMeep contributors.
// SPDX-License-Identifier: MIT
//
// Open D3D12 host for NVIDIA NGX DLSS Frame Generation. NVIDIA's NGX SDK and
// nvngx_dlssg.dll are separate proprietary components and are not distributed
// by this project. This process intentionally keeps the original WanGP worker
// protocol so it can replace the closed Merserk worker without Python changes.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <fcntl.h>
#include <io.h>

#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

#include <nvsdk_ngx.h>
#include <nvsdk_ngx_helpers_dlssg_d3d.h>
#include "ampere_provider.h"
#include "ampere_bridge.h"

namespace {

constexpr uint32_t SETUP_MAGIC = 0x31534746;
constexpr uint32_t SETUP_OUT_MAGIC = 0x31524746;
constexpr uint32_t FRAME_MAGIC = 0x31464746;
constexpr uint32_t FRAME_OUT_MAGIC = 0x314F4746;
constexpr char PROJECT_ID[] = "6d648dba-bac0-44ef-8e49-d8291d756f37";

struct SetupHeader {
    uint32_t magic, width, height, frame_count, generated_count;
};

struct SetupResult {
    uint32_t magic, status, maximum, reserved;
};

struct FrameHeader {
    uint32_t magic, index, reset, reserved;
    int64_t timestamp_numerator, timestamp_denominator;
};

struct FrameResult {
    uint32_t magic, status, generated, disabled;
};

static_assert(sizeof(SetupHeader) == 20);
static_assert(sizeof(FrameHeader) == 32);

template<class T> void Release(T *&value) {
    if (value != nullptr) {
        value->Release();
        value = nullptr;
    }
}

bool ReadExact(void *data, size_t size) {
    auto *target = static_cast<uint8_t *>(data);
    while (size != 0) {
        const size_t count = fread(target, 1, size, stdin);
        if (count == 0) return false;
        target += count;
        size -= count;
    }
    return true;
}

bool WriteExact(const void *data, size_t size) {
    const auto *source = static_cast<const uint8_t *>(data);
    while (size != 0) {
        const size_t count = fwrite(source, 1, size, stdout);
        if (count == 0) return false;
        source += count;
        size -= count;
    }
    fflush(stdout);
    return true;
}

void Log(const char *format, ...) {
    va_list args;
    va_start(args, format);
    vfprintf(stderr, format, args);
    va_end(args);
    fputc('\n', stderr);
    fflush(stderr);
}

D3D12_RESOURCE_DESC BufferDesc(uint64_t size, D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    D3D12_RESOURCE_DESC desc = {};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = size;
    desc.Height = 1;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    desc.Flags = flags;
    return desc;
}

D3D12_RESOURCE_DESC TextureDesc(uint32_t width, uint32_t height, DXGI_FORMAT format, D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    D3D12_RESOURCE_DESC desc = {};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = width;
    desc.Height = height;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.Format = format;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    desc.Flags = flags;
    return desc;
}

D3D12_RESOURCE_BARRIER Transition(ID3D12Resource *resource, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
    D3D12_RESOURCE_BARRIER barrier = {};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = resource;
    barrier.Transition.StateBefore = before;
    barrier.Transition.StateAfter = after;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    return barrier;
}

std::string FileVersion(const wchar_t *directory) {
    wchar_t path[MAX_PATH] = {};
    swprintf_s(path, L"%ls\\nvngx_dlssg.dll", directory);
    DWORD ignored = 0;
    const DWORD size = GetFileVersionInfoSizeW(path, &ignored);
    if (size == 0) return "unknown";
    std::vector<uint8_t> data(size);
    if (!GetFileVersionInfoW(path, 0, size, data.data())) return "unknown";
    VS_FIXEDFILEINFO *info = nullptr;
    UINT info_size = 0;
    if (!VerQueryValueW(data.data(), L"\\", reinterpret_cast<void **>(&info), &info_size) || info == nullptr) return "unknown";
    char version[64] = {};
    sprintf_s(version, "%u.%u.%u.%u", HIWORD(info->dwFileVersionMS), LOWORD(info->dwFileVersionMS), HIWORD(info->dwFileVersionLS), LOWORD(info->dwFileVersionLS));
    return version;
}

class Worker {
public:
    ~Worker() { Shutdown(); }

    bool Initialize(const char *requested_luid, const wchar_t *provider_path) {
        std::string provider_detail;
        if (provider_path == nullptr || !provider_.LoadAndAdapt(provider_path, provider_detail)) {
            Log("PROVIDER_ADAPTATION_FAILED: %s", provider_detail.c_str());
            return false;
        }
        Log("PROVIDER_IDENTITY_VERIFIED");
        Log("PROVIDER_PRELOADED");
        Log("PROVIDER_MAPPING_VERIFIED");
        Log("PROVIDER_EDIT_PLAN_READY edits=%zu hidden_cubins=%zu", provider_.edit_count(), provider_.hidden_cubins());
        Log("PROVIDER_EDITS_APPLIED"); Log("PROVIDER_EDITS_VERIFIED");
        SetEnvironmentVariableW(L"NGX_DISABLE_UPDATER", L"1");
        UINT factory_flags = 0;
        if (FAILED(CreateDXGIFactory2(factory_flags, IID_PPV_ARGS(&factory_)))) return Fail("CreateDXGIFactory2 failed");

        uint64_t wanted_luid = 0;
        bool select_luid = false;
        if (requested_luid != nullptr) {
            char *end = nullptr;
            wanted_luid = _strtoui64(requested_luid, &end, 16);
            select_luid = end != requested_luid && *end == '\0';
            if (!select_luid) return Fail("invalid --adapter-luid value");
        }

        for (UINT index = 0;; ++index) {
            IDXGIAdapter1 *candidate = nullptr;
            if (factory_->EnumAdapters1(index, &candidate) == DXGI_ERROR_NOT_FOUND) break;
            DXGI_ADAPTER_DESC1 desc = {};
            candidate->GetDesc1(&desc);
            const uint64_t luid = (static_cast<uint64_t>(static_cast<uint32_t>(desc.AdapterLuid.HighPart)) << 32) | desc.AdapterLuid.LowPart;
            fwprintf(stderr, L"Adapter %u: %ls, LUID %08X:%08X\n", index, desc.Description, static_cast<uint32_t>(desc.AdapterLuid.HighPart), desc.AdapterLuid.LowPart);
            if (!(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) && (!select_luid || luid == wanted_luid)) {
                adapter_ = candidate;
                break;
            }
            candidate->Release();
        }
        if (adapter_ == nullptr) return Fail("no compatible DXGI adapter found");

        std::string bridge_detail;
        if (!bridge_.Initialize(bridge_detail) || !bridge_.BindAdapter(adapter_, bridge_detail) ||
            !bridge_.PrepareProvider(provider_, bridge_detail)) return Fail(bridge_detail.c_str());
        Log("NVAPI_ADAPTER_BOUND"); Log("NVAPI_HOOK_INSTALLED"); Log("SCOPED_BRIDGE_READY: %s", bridge_detail.c_str());

        if (FAILED(D3D12CreateDevice(adapter_, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device_))))
            return Fail("selected adapter could not create a D3D12 device");
        Log("D3D12_DEVICE_CREATED");

        D3D12_COMMAND_QUEUE_DESC queue_desc = {};
        queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (FAILED(device_->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue_))) ||
            FAILED(device_->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator_))) ||
            FAILED(device_->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator_, nullptr, IID_PPV_ARGS(&list_))) ||
            FAILED(device_->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence_)))) return Fail("D3D12 command objects could not be created");
        event_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (event_ == nullptr || FAILED(list_->Close())) return Fail("D3D12 fence event could not be created");

        wchar_t executable[MAX_PATH] = {};
        GetModuleFileNameW(nullptr, executable, MAX_PATH);
        wchar_t *slash = wcsrchr(executable, L'\\');
        if (slash != nullptr) *slash = L'\0';
        runtime_version_ = FileVersion(executable);
        const wchar_t *paths[] = {executable};
        NVSDK_NGX_FeatureCommonInfo info = {};
        info.PathListInfo.Path = paths;
        info.PathListInfo.Length = 1;
        NVSDK_NGX_FeatureDiscoveryInfo discovery = {};
        discovery.SDKVersion = NVSDK_NGX_Version_API;
        discovery.FeatureID = NVSDK_NGX_Feature_FrameGeneration;
        discovery.Identifier.IdentifierType = NVSDK_NGX_Application_Identifier_Type_Project_Id;
        discovery.Identifier.v.ProjectDesc = {PROJECT_ID, NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0"};
        discovery.ApplicationDataPath = executable;
        discovery.FeatureInfo = &info;
        NVSDK_NGX_FeatureRequirement requirements = {};
        const NVSDK_NGX_Result requirement_result = bridge_.Requirements(
            adapter_, &discovery, &requirements, &NVSDK_NGX_D3D12_GetFeatureRequirements);
        Log("DLSSG_REQUIREMENTS result=0x%08X FeatureSupported=0x%X MinHW=0x%X final=0x%X/0x%X",
            requirement_result, static_cast<unsigned>(requirements.FeatureSupported),
            requirements.MinHWArchitecture, static_cast<unsigned>(requirements.FeatureSupported),
            requirements.MinHWArchitecture);
        if (NVSDK_NGX_FAILED(requirement_result)) return false;
        const NVSDK_NGX_Result init = NVSDK_NGX_D3D12_Init_with_ProjectID(PROJECT_ID, NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0", executable, device_, &info, NVSDK_NGX_Version_API);
        Log("NGX_INIT_RESULT 0x%08X", init);
        if (NVSDK_NGX_FAILED(init)) {
            Log("NGX initialization failed: 0x%08X", init);
            return false;
        }
        ngx_initialized_ = true;
        const NVSDK_NGX_Result capabilities = bridge_.GetCapabilities(&parameters_, &NVSDK_NGX_D3D12_GetCapabilityParameters);
        if (NVSDK_NGX_FAILED(capabilities) || parameters_ == nullptr) {
            Log("NGX capability query failed: 0x%08X", capabilities);
            return false;
        }
        int available = 0;
        int maximum = 0;
        if (static_cast<int>(parameters_->Get(NVSDK_NGX_Parameter_FrameGeneration_Available, &available)) != static_cast<int>(NVSDK_NGX_Result_Success) ||
            static_cast<int>(parameters_->Get(NVSDK_NGX_DLSSG_Parameter_MultiFrameCountMax, &maximum)) != static_cast<int>(NVSDK_NGX_Result_Success)) {
            Log("CAPABILITY_READ_FAILED"); return false;
        }
        maximum_ = maximum > 1 ? 1u : maximum < 0 ? 0u : static_cast<uint32_t>(maximum);
        available_ = available != 0;
        return true;
    }

    bool available() const { return available_; }
    uint32_t maximum() const { return maximum_; }
    const std::string &runtime_version() const { return runtime_version_; }

    bool CreateFeature(uint32_t width, uint32_t height, uint32_t generated_count) {
        if (generated_count != 1) { Log("2X_ONLY_REJECTED generated_count=%u", generated_count); return false; }
        width_ = width;
        height_ = height;
        generated_count_ = generated_count;
        if (!CreateTexture(color_, width, height, DXGI_FORMAT_R8G8B8A8_UNORM, width * 4) ||
            !CreateTexture(motion_, width, height, DXGI_FORMAT_R16G16_FLOAT, width * 4) ||
            !CreateTexture(depth_, width, height, DXGI_FORMAT_R32_FLOAT, width * 4) ||
            !CreateOutput() || !CreateDisableOutput()) return false;

        std::vector<float> depth(static_cast<size_t>(width_) * height_, 0.5f);
        if (!FillUpload(depth_, depth.data(), width_ * sizeof(float))) return false;
        if (!Begin()) return false;
        CopyUpload(depth_);
        auto depth_ready = Transition(depth_.texture, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        list_->ResourceBarrier(1, &depth_ready);
        if (!SubmitAndWait()) return false;
        Log("D3D12_UPLOAD_COMPLETE");
        depth_.ready = true;

        const uint32_t always = NVSDK_NGX_DLSSG_ResourceFlags_Backbuffer | NVSDK_NGX_DLSSG_ResourceFlags_MVecs |
            NVSDK_NGX_DLSSG_ResourceFlags_Depth | NVSDK_NGX_DLSSG_ResourceFlags_HUDLess |
            NVSDK_NGX_DLSSG_ResourceFlags_OutputInterpolated | NVSDK_NGX_DLSSG_ResourceFlags_OutputDisableInterpolation;
        const uint32_t never = NVSDK_NGX_DLSSG_ResourceFlags_UI | NVSDK_NGX_DLSSG_ResourceFlags_UIAlpha |
            NVSDK_NGX_DLSSG_ResourceFlags_BidirectionalDistortionField | NVSDK_NGX_DLSSG_ResourceFlags_OutputReal;
        parameters_->Set(NVSDK_NGX_DLSSG_Parameter_ResourceAlwaysProvided_Flags, always);
        parameters_->Set(NVSDK_NGX_DLSSG_Parameter_ResourceNeverProvided_Flags, never);
        parameters_->Set(NVSDK_NGX_DLSSG_Parameter_UserInterfaceRecompositionEnabled, 0u);
        parameters_->Set(NVSDK_NGX_DLSSG_Parameter_Width, width_);
        parameters_->Set(NVSDK_NGX_DLSSG_Parameter_Height, height_);

        NVSDK_NGX_DLSSG_Create_Params create = {};
        create.Width = width_;
        create.Height = height_;
        create.NativeBackbufferFormat = DXGI_FORMAT_R8G8B8A8_UNORM;
        create.RenderWidth = width_;
        create.RenderHeight = height_;
        create.DynamicResolutionScaling = false;
        if (!Begin()) return false;
        const NVSDK_NGX_Result result = NGX_D3D12_CREATE_DLSSG(list_, 1, 1, &feature_, parameters_, &create);
        if (NVSDK_NGX_FAILED(result)) {
            Log("DLSSG feature creation failed: 0x%08X", result);
            list_->Close();
            return false;
        }
        if (!SubmitAndWait()) return false;
        Log("FEATURE_CREATE_WAIT_COMPLETE");
        Log("DLSSG feature created at %ux%u, maximum generated frames %u", width_, height_, maximum_);
        return true;
    }

    bool Upload(const uint8_t *rgba, const uint8_t *motion) {
        if (!FillUpload(color_, rgba, width_ * 4) || !FillUpload(motion_, motion, width_ * 4) || !Begin()) return false;
        Texture *items[] = {&color_, &motion_};
        for (Texture *item : items) {
            if (item->ready) {
                auto to_copy = Transition(item->texture, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
                list_->ResourceBarrier(1, &to_copy);
            }
            CopyUpload(*item);
            auto ready = Transition(item->texture, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            list_->ResourceBarrier(1, &ready);
            item->ready = true;
        }
        return SubmitAndWait();
    }

    NVSDK_NGX_Result EvaluateGroup(uint32_t frame_id, bool reset, std::vector<std::vector<uint8_t>> &frames, bool &disabled) {
        if (!Begin()) return static_cast<NVSDK_NGX_Result>(0x7FFFFFFF);
        NVSDK_NGX_Result result = NVSDK_NGX_Result_Success;
        for (uint32_t index = 1; index <= generated_count_; ++index) {
            auto disable_to_copy = Transition(disable_, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_DEST);
            list_->ResourceBarrier(1, &disable_to_copy);
            list_->CopyBufferRegion(disable_, 0, disable_zero_, 0, 4);
            auto disable_to_uav = Transition(disable_, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            list_->ResourceBarrier(1, &disable_to_uav);

            parameters_->Set(NVSDK_NGX_DLSSG_Parameter_BackbufferFrameID, static_cast<unsigned long long>(frame_id));
            NVSDK_NGX_D3D12_DLSSG_Eval_Params eval = {};
            eval.pBackbuffer = color_.texture;
            eval.pDepth = depth_.texture;
            eval.pMVecs = motion_.texture;
            eval.pHudless = color_.texture;
            eval.pOutputInterpFrame = output_;
            eval.pOutputDisableInterpolation = disable_;

            NVSDK_NGX_DLSSG_Opt_Eval_Params options = {};
            options.multiFrameCount = 1;
            options.multiFrameIndex = index;
            Identity(options.cameraViewToClip);
            Identity(options.clipToCameraView);
            Identity(options.clipToLensClip);
            Identity(options.clipToPrevClip);
            Identity(options.prevClipToClip);
            options.mvecScale[0] = 1.0f / width_;
            options.mvecScale[1] = 1.0f / height_;
            options.cameraNear = 0.1f;
            options.cameraFar = 1000.0f;
            options.cameraFOV = 1.04719755f;
            options.cameraAspectRatio = static_cast<float>(width_) / height_;
            options.reset = reset;
            options.orthoProjection = true;
            options.motionVectorsInvalidValue = -65500.0f;
            options.motionVectorsDilated = true;
            options.mvecsSubrectSize = {width_, height_};
            options.depthSubrectSize = {width_, height_};
            options.hudLessSubrectSize = {width_, height_};
            options.backbufferSubrectSize = {width_, height_};
            options.outputInterpSubrectSize = {width_, height_};

            result = NGX_D3D12_EVALUATE_DLSSG(list_, feature_, parameters_, &eval, &options);
            if (NVSDK_NGX_FAILED(result)) {
                Log("DLSSG evaluate failed for frame %u index %u/%u: 0x%08X", frame_id, index, generated_count_, result);
                list_->Close();
                return result;
            }

            D3D12_RESOURCE_BARRIER barriers[] = {
                Transition(output_, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE),
                Transition(disable_, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE),
            };
            list_->ResourceBarrier(2, barriers);
            D3D12_TEXTURE_COPY_LOCATION source = {}, destination = {};
            source.pResource = output_;
            source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            destination.pResource = output_readback_;
            destination.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            destination.PlacedFootprint = output_footprint_;
            destination.PlacedFootprint.Offset = static_cast<uint64_t>(index - 1) * output_stride_;
            list_->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
            list_->CopyBufferRegion(disable_readback_, static_cast<uint64_t>(index - 1) * 4, disable_, 0, 4);
            std::swap(barriers[0].Transition.StateBefore, barriers[0].Transition.StateAfter);
            std::swap(barriers[1].Transition.StateBefore, barriers[1].Transition.StateAfter);
            list_->ResourceBarrier(2, barriers);
        }
        if (!SubmitAndWait()) return static_cast<NVSDK_NGX_Result>(0x7FFFFFFF);
        Log(reset ? "RESET_EVALUATE_RESULT" : "MEASURED_EVALUATE_RESULT");

        uint8_t *mapped = nullptr;
        D3D12_RANGE disable_range = {0, static_cast<SIZE_T>(generated_count_) * 4};
        if (FAILED(disable_readback_->Map(0, &disable_range, reinterpret_cast<void **>(&mapped)))) return static_cast<NVSDK_NGX_Result>(0x7FFFFFFF);
        disabled = false;
        for (uint32_t index = 0; index < generated_count_; ++index) disabled |= mapped[index * 4] != 0;
        D3D12_RANGE empty = {0, 0};
        disable_readback_->Unmap(0, &empty);

        const size_t packed_pitch = static_cast<size_t>(width_) * 4;
        D3D12_RANGE output_range = {0, static_cast<SIZE_T>(output_stride_) * generated_count_};
        if (FAILED(output_readback_->Map(0, &output_range, reinterpret_cast<void **>(&mapped)))) return static_cast<NVSDK_NGX_Result>(0x7FFFFFFF);
        frames.assign(generated_count_, std::vector<uint8_t>(packed_pitch * height_));
        for (uint32_t index = 0; index < generated_count_; ++index)
            for (uint32_t row = 0; row < height_; ++row)
                memcpy(frames[index].data() + static_cast<size_t>(row) * packed_pitch,
                       mapped + static_cast<uint64_t>(index) * output_stride_ + static_cast<size_t>(row) * output_footprint_.Footprint.RowPitch, packed_pitch);
        output_readback_->Unmap(0, &empty);
        return result;
    }

private:
    struct Texture {
        ID3D12Resource *texture = nullptr;
        ID3D12Resource *upload = nullptr;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint = {};
        bool ready = false;
    };

    static void Identity(float matrix[4][4]) {
        memset(matrix, 0, sizeof(float) * 16);
        matrix[0][0] = matrix[1][1] = matrix[2][2] = matrix[3][3] = 1.0f;
    }

    bool Fail(const char *message) {
        Log("%s", message);
        return false;
    }

    bool Begin() {
        return SUCCEEDED(allocator_->Reset()) && SUCCEEDED(list_->Reset(allocator_, nullptr));
    }

    bool SubmitAndWait() {
        if (FAILED(list_->Close())) return false;
        ID3D12CommandList *lists[] = {list_};
        queue_->ExecuteCommandLists(1, lists);
        const uint64_t value = ++fence_value_;
        if (FAILED(queue_->Signal(fence_, value))) return false;
        if (fence_->GetCompletedValue() < value) {
            if (FAILED(fence_->SetEventOnCompletion(value, event_))) return false;
            const DWORD wait = WaitForSingleObject(event_, 15000);
            if (wait != WAIT_OBJECT_0) { Log("FENCE_WAIT_RESULT timeout=%lu", static_cast<unsigned long>(wait)); Log("DEVICE_HEALTH fence_wait=0x%08X", device_->GetDeviceRemovedReason()); return false; }
        }
        const HRESULT removed = device_->GetDeviceRemovedReason();
        if (FAILED(removed)) {
            Log("D3D12 device removed: 0x%08X", removed);
            return false;
        }
        return true;
    }

    bool CreateTexture(Texture &item, uint32_t width, uint32_t height, DXGI_FORMAT format, uint32_t packed_pitch) {
        D3D12_HEAP_PROPERTIES heap = {};
        heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        const D3D12_RESOURCE_DESC texture = TextureDesc(width, height, format);
        if (FAILED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture, D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&item.texture)))) return false;
        UINT rows = 0;
        uint64_t row_size = 0, total = 0;
        device_->GetCopyableFootprints(&texture, 0, 1, 0, &item.footprint, &rows, &row_size, &total);
        if (rows != height || row_size < packed_pitch) return false;
        heap.Type = D3D12_HEAP_TYPE_UPLOAD;
        const D3D12_RESOURCE_DESC upload = BufferDesc(total);
        return SUCCEEDED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &upload, D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&item.upload)));
    }

    bool CreateOutput() {
        D3D12_HEAP_PROPERTIES heap = {};
        heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        const D3D12_RESOURCE_DESC texture = TextureDesc(width_, height_, DXGI_FORMAT_R8G8B8A8_UNORM, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        if (FAILED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, nullptr, IID_PPV_ARGS(&output_)))) return false;
        UINT rows = 0;
        uint64_t row_size = 0, total = 0;
        device_->GetCopyableFootprints(&texture, 0, 1, 0, &output_footprint_, &rows, &row_size, &total);
        output_stride_ = (total + D3D12_TEXTURE_DATA_PLACEMENT_ALIGNMENT - 1) & ~(static_cast<uint64_t>(D3D12_TEXTURE_DATA_PLACEMENT_ALIGNMENT) - 1);
        heap.Type = D3D12_HEAP_TYPE_READBACK;
        const D3D12_RESOURCE_DESC readback = BufferDesc(output_stride_ * generated_count_);
        return SUCCEEDED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &readback, D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&output_readback_)));
    }

    bool CreateDisableOutput() {
        D3D12_HEAP_PROPERTIES heap = {};
        heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        const D3D12_RESOURCE_DESC output = BufferDesc(4, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        if (FAILED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &output, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, nullptr, IID_PPV_ARGS(&disable_)))) return false;
        heap.Type = D3D12_HEAP_TYPE_UPLOAD;
        const D3D12_RESOURCE_DESC staging = BufferDesc(4);
        if (FAILED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &staging, D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&disable_zero_)))) return false;
        uint8_t *mapped = nullptr;
        if (FAILED(disable_zero_->Map(0, nullptr, reinterpret_cast<void **>(&mapped)))) return false;
        memset(mapped, 0, 4);
        disable_zero_->Unmap(0, nullptr);
        heap.Type = D3D12_HEAP_TYPE_READBACK;
        const D3D12_RESOURCE_DESC readback = BufferDesc(static_cast<uint64_t>(generated_count_) * 4);
        return SUCCEEDED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &readback, D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&disable_readback_)));
    }

    bool FillUpload(Texture &item, const void *data, uint32_t packed_pitch) {
        uint8_t *mapped = nullptr;
        if (FAILED(item.upload->Map(0, nullptr, reinterpret_cast<void **>(&mapped)))) return false;
        const auto *source = static_cast<const uint8_t *>(data);
        for (uint32_t row = 0; row < height_; ++row)
            memcpy(mapped + static_cast<size_t>(row) * item.footprint.Footprint.RowPitch, source + static_cast<size_t>(row) * packed_pitch, packed_pitch);
        item.upload->Unmap(0, nullptr);
        return true;
    }

    void CopyUpload(Texture &item) {
        D3D12_TEXTURE_COPY_LOCATION source = {}, destination = {};
        source.pResource = item.upload;
        source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        source.PlacedFootprint = item.footprint;
        destination.pResource = item.texture;
        destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        list_->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
    }

    void Shutdown() {
        if (feature_ != nullptr) {
            const NVSDK_NGX_Result result = NVSDK_NGX_D3D12_ReleaseFeature(feature_);
            Log("FEATURE_RELEASE_RESULT 0x%08X", result);
            feature_ = nullptr;
        }
        if (parameters_ != nullptr) {
            NVSDK_NGX_D3D12_DestroyParameters(parameters_);
            parameters_ = nullptr;
        }
        if (ngx_initialized_) { const NVSDK_NGX_Result result = NVSDK_NGX_D3D12_Shutdown1(device_); Log("NGX_SHUTDOWN_RESULT 0x%08X", result); }
        bridge_.Shutdown();
        Log("NVAPI_HOOK_REMOVAL_RESULT installed=%d", bridge_.HookInstalled() ? 1 : 0);
        provider_.Rollback();
        Log("PROVIDER_ROLLBACK_RESULT");
        Release(color_.texture); Release(color_.upload);
        Release(motion_.texture); Release(motion_.upload);
        Release(depth_.texture); Release(depth_.upload);
        Release(output_); Release(output_readback_);
        Release(disable_); Release(disable_zero_); Release(disable_readback_);
        Release(list_); Release(allocator_); Release(fence_); Release(queue_);
        Release(device_); Release(adapter_); Release(factory_);
        if (event_ != nullptr) CloseHandle(event_);
        event_ = nullptr;
    }

    IDXGIFactory6 *factory_ = nullptr;
    IDXGIAdapter1 *adapter_ = nullptr;
    ID3D12Device *device_ = nullptr;
    ID3D12CommandQueue *queue_ = nullptr;
    ID3D12CommandAllocator *allocator_ = nullptr;
    ID3D12GraphicsCommandList *list_ = nullptr;
    ID3D12Fence *fence_ = nullptr;
    HANDLE event_ = nullptr;
    uint64_t fence_value_ = 0;
    NVSDK_NGX_Parameter *parameters_ = nullptr;
    NVSDK_NGX_Handle *feature_ = nullptr;
    bool ngx_initialized_ = false;
    bool available_ = false;
    std::string runtime_version_ = "unknown";
    uint32_t maximum_ = 1;
    uint32_t width_ = 0, height_ = 0, generated_count_ = 1;
    Texture color_, motion_, depth_;
    ampere_provider::Session provider_;
    ampere_bridge::Bridge bridge_;
    ID3D12Resource *output_ = nullptr, *output_readback_ = nullptr;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT output_footprint_ = {};
    uint64_t output_stride_ = 0;
    ID3D12Resource *disable_ = nullptr, *disable_zero_ = nullptr, *disable_readback_ = nullptr;
};

int Probe(Worker &worker) {
    printf("{\"available\":%s,\"multi_frame_count_max\":%u,\"runtime_version\":\"%s\",\"worker_version\":\"2\",\"detail\":\"Open D3D12 NGX capability query completed.\"}\n",
           worker.available() ? "true" : "false", worker.maximum(), worker.runtime_version().c_str());
    return worker.available() ? 0 : 2;
}

int Serve(Worker &worker) {
    SetupHeader setup = {};
    if (!ReadExact(&setup, sizeof(setup)) || setup.magic != SETUP_MAGIC || setup.width < 64 || setup.height < 64 ||
        setup.width > 7680 || setup.height > 4320 || setup.frame_count == 0 || setup.generated_count == 0) return 2;
    uint32_t status = 0;
    if (!worker.available()) status = 1;
    else if (setup.generated_count > worker.maximum()) status = 2;
    else if (!worker.CreateFeature(setup.width, setup.height, setup.generated_count)) status = 3;
    const SetupResult setup_result = {SETUP_OUT_MAGIC, status, worker.maximum(), 0};
    if (!WriteExact(&setup_result, sizeof(setup_result)) || status != 0) return status ? static_cast<int>(status) : 3;

    const size_t frame_bytes = static_cast<size_t>(setup.width) * setup.height * 4;
    std::vector<uint8_t> rgba(frame_bytes), motion(frame_bytes);
    for (uint32_t frame_number = 0; frame_number < setup.frame_count; ++frame_number) {
        FrameHeader frame = {};
        if (!ReadExact(&frame, sizeof(frame)) || frame.magic != FRAME_MAGIC || !ReadExact(rgba.data(), rgba.size()) || !ReadExact(motion.data(), motion.size())) return 4;
        uint32_t frame_status = 0, generated_count = 0, disabled = 0;
        std::vector<std::vector<uint8_t>> outputs;
        if (!worker.Upload(rgba.data(), motion.data())) frame_status = 5;
        bool output_disabled = false;
        const NVSDK_NGX_Result result = frame_status == 0 ? worker.EvaluateGroup(frame.index, frame.reset != 0, outputs, output_disabled) : static_cast<NVSDK_NGX_Result>(0x7FFFFFFF);
        if (NVSDK_NGX_FAILED(result)) {
            frame_status = static_cast<uint32_t>(result);
            if (frame_status == 0 || frame_status == 1) frame_status = 6;
        }
        if (output_disabled) {
            disabled = 1;
            outputs.clear();
        }
        if (frame.reset) outputs.clear();
        generated_count = static_cast<uint32_t>(outputs.size());
        const FrameResult frame_result = {FRAME_OUT_MAGIC, frame_status, generated_count, disabled};
        if (!WriteExact(&frame_result, sizeof(frame_result))) return 7;
        for (const auto &output : outputs)
            if (!WriteExact(output.data(), output.size())) return 7;
    }
    return 0;
}

} // namespace

int main(int argc, char **argv) {
    bool probe = false, serve = false;
    const char *adapter_luid = nullptr;
    std::wstring provider_path;
    for (int index = 1; index < argc; ++index) {
        if (strcmp(argv[index], "--probe") == 0) probe = true;
        else if (strcmp(argv[index], "--serve") == 0) serve = true;
        else if (strcmp(argv[index], "--adapter-luid") == 0 && index + 1 < argc) adapter_luid = argv[++index];
        else if (strcmp(argv[index], "--provider") == 0 && index + 1 < argc) {
            const char *value = argv[++index];
            provider_path.assign(value, value + strlen(value));
        }
        else {
            fprintf(stderr, "Usage: dlssg-worker.exe --probe|--serve [--adapter-luid <16hex>]\n");
            return 1;
        }
    }
    if (probe == serve) {
        fprintf(stderr, "Usage: dlssg-worker.exe --probe|--serve [--adapter-luid <16hex>]\n");
        return 1;
    }
    if (serve) {
        if (_setmode(_fileno(stdin), _O_BINARY) == -1 || _setmode(_fileno(stdout), _O_BINARY) == -1) return 2;
    }
    Worker worker;
    if (provider_path.empty()) {
        fprintf(stderr, "--provider <absolute nvngx_dlssg.dll path> is required\n");
        return 2;
    }
    if (!worker.Initialize(adapter_luid, provider_path.c_str())) return 2;
    return probe ? Probe(worker) : Serve(worker);
}
