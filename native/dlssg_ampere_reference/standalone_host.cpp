// Copyright (c) 2026 DeepBeepMeep contributors.
// SPDX-License-Identifier: MIT
//
// Standalone one-shot D3D12 host for NVIDIA NGX DLSS Frame Generation.
// The host is adapted from the useful D3D12 portions of Phase 3; it does not
// retain the old stdin/pipe worker protocol.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <psapi.h>
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
#include <nvsdk_ngx_helpers_dlssg.h>
#include "ampere_provider.h"
#include "ampere_bridge.h"
#include "reference_core.hpp"
#include "provider_memory.h"

namespace {

void Stage(const char* text) {
    std::fprintf(stderr, "%s\n", text);
    std::fflush(stderr);
}

constexpr char PROJECT_ID[] = "6d648dba-bac0-44ef-8e49-d8291d756f37";

template<class T> void Release(T *&value) {
    if (value != nullptr) {
        value->Release();
        value = nullptr;
    }
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
        Log("PROVIDER_LOADED");
        Log("PROVIDER_MAPPING_VERIFIED");
        LogProviderIdentity();
        Log("PROVIDER_EDIT_PLAN_READY edits=%zu hidden_cubins=%zu", provider_.edit_count(), provider_.hidden_cubins());
        Log("PROVIDER_ADAPTED");
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
            if (!(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) &&
                (wcsstr(desc.Description, L"RTX 3070 Ti") != nullptr) &&
                (!select_luid || luid == wanted_luid)) {
                adapter_ = candidate;
                Log("GPU_IDENTIFIED");
                break;
            }
            candidate->Release();
        }
        if (adapter_ == nullptr) return Fail("no compatible DXGI adapter found");

        std::string bridge_detail;
        if (!bridge_.Initialize(bridge_detail) || !bridge_.BindAdapter(adapter_, bridge_detail) ||
            !bridge_.PrepareProvider(provider_, bridge_detail)) return Fail(bridge_detail.c_str());
        Log("NVAPI_TARGET_RESOLVED");
        Log("AMPERE_NATIVE_ARCH=0x%X", ampere_provider::kNativeArchitecture);
        Log("AMPERE_EXPOSED_ARCH=0x%X", ampere_provider::kAdaArchitecture);
        Log("AMPERE_BRIDGE_READY");

        if (FAILED(D3D12CreateDevice(adapter_, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device_))))
            return Fail("selected adapter could not create a D3D12 device");
        Log("D3D12_CREATED");

        D3D12_COMMAND_QUEUE_DESC queue_desc = {};
        queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (FAILED(device_->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue_))) ||
            FAILED(device_->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator_))) ||
            FAILED(device_->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator_, nullptr, IID_PPV_ARGS(&list_))) ||
            FAILED(device_->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence_)))) return Fail("D3D12 command objects could not be created");
        Log("QUEUE_CREATED");
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
        Log("NGX_INIT_STARTED");
        const NVSDK_NGX_Result init = NVSDK_NGX_D3D12_Init_with_ProjectID(PROJECT_ID, NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0", executable, device_, &info, NVSDK_NGX_Version_API);
        Log("NGX_INIT_RESULT 0x%08X", init);
        if (NVSDK_NGX_FAILED(init)) {
            Log("NGX initialization failed: 0x%08X", init);
            return false;
        }
        ngx_initialized_ = true;
        Log("CAPABILITY_QUERY_STARTED");
        const NVSDK_NGX_Result capabilities = bridge_.GetCapabilities(&parameters_, &NVSDK_NGX_D3D12_GetCapabilityParameters);
        Log("CAPABILITY_QUERY_RESULT=0x%08X", capabilities);
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
        Log("FG_AVAILABLE=%d", available_ ? 1 : 0);
        Log("MULTIFRAME_MAX=%u", maximum_);
        return true;
    }

    void LogProviderIdentity() const {
        wchar_t path[32768] = {};
        const DWORD length = GetModuleFileNameW(provider_.module(), path, ARRAYSIZE(path));
        Log("PROVIDER_MODULE_BASE=0x%p", provider_.module());
        if (length != 0 && length < ARRAYSIZE(path)) {
            std::string narrow(length, '\0');
            WideCharToMultiByte(CP_UTF8, 0, path, static_cast<int>(length), narrow.data(),
                                static_cast<int>(narrow.size()), nullptr, nullptr);
            Log("PROVIDER_MODULE_PATH=%s", narrow.c_str());
        }
        std::string detail;
        Log("PROVIDER_EDIT_READBACK=%d", provider_.VerifyReadback(detail) ? 1 : 0);
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
        Log("CREATE_STARTED");
        const NVSDK_NGX_Result result = NGX_D3D12_CREATE_DLSSG(list_, 1, 1, &feature_, parameters_, &create);
        Log("CREATE_RESULT=0x%08X", result);
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

            Log(reset ? "RESET_EVAL_STARTED" : "MEASURED_EVAL_STARTED");
            result = NGX_D3D12_EVALUATE_DLSSG(list_, feature_, parameters_, &eval, &options);
            Log(reset ? "RESET_EVAL_RESULT=0x%08X" : "MEASURED_EVAL_RESULT=0x%08X", result);
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

        Log("READBACK_STARTED");
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
        Log("READBACK_COMPLETE");
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
        Log("FENCE_WAIT_STARTED");
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
        Log("FENCE_WAIT_RESULT=1");
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

} // namespace

std::string Sha256(const std::vector<uint8_t>& bytes) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    DWORD object_size = 0, hash_size = 0, ignored = 0;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0 ||
        BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size), &ignored, 0) < 0 ||
        BCryptGetProperty(algorithm, BCRYPT_HASH_LENGTH, reinterpret_cast<PUCHAR>(&hash_size), sizeof(hash_size), &ignored, 0) < 0) return {};
    std::vector<uint8_t> object(object_size), digest(hash_size);
    if (BCryptCreateHash(algorithm, &hash, object.data(), object_size, nullptr, 0, 0) < 0 ||
        BCryptHashData(hash, const_cast<PUCHAR>(bytes.data()), static_cast<ULONG>(bytes.size()), 0) < 0 ||
        BCryptFinishHash(hash, digest.data(), hash_size, 0) < 0) { if (hash) BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(algorithm, 0); return {}; }
    BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(algorithm, 0);
    char text[65] = {};
    for (DWORD i = 0; i < hash_size; ++i) sprintf_s(text + i * 2, 3, "%02X", digest[i]);
    return text;
}

uint16_t FloatToHalf(float value) {
    uint32_t bits = 0; memcpy(&bits, &value, sizeof(bits));
    const uint32_t sign = (bits >> 16) & 0x8000u;
    const int exponent = static_cast<int>((bits >> 23) & 0xffu) - 127 + 15;
    const uint32_t mantissa = bits & 0x7fffffu;
    if (exponent <= 0) return static_cast<uint16_t>(sign);
    if (exponent >= 31) return static_cast<uint16_t>(sign | 0x7c00u);
    return static_cast<uint16_t>(sign | (static_cast<uint32_t>(exponent) << 10) | (mantissa >> 13));
}

std::vector<uint8_t> MakeColor(unsigned x) {
    std::vector<uint8_t> color(256u * 256u * 4u, 0);
    for (unsigned y = 64; y < 128; ++y) for (unsigned px = x; px < x + 64; ++px) {
        const size_t at = (static_cast<size_t>(y) * 256u + px) * 4u;
        color[at + 0] = 255; color[at + 3] = 255;
    }
    return color;
}

std::vector<uint8_t> MakeMotion(float x, float y) {
    std::vector<uint8_t> motion(256u * 256u * 4u);
    const uint16_t hx = FloatToHalf(x), hy = FloatToHalf(y);
    for (size_t at = 0; at < motion.size(); at += 4) { memcpy(motion.data() + at, &hx, 2); memcpy(motion.data() + at + 2, &hy, 2); }
    return motion;
}

int SelfTest() {
    using namespace dlssg_ampere_reference;
    if (!IsAmpere(kNvidiaVendor, kAmpereArchitecture, 1) ||
        GeneratedFramesForMultiplier(2) != 1 ||
        !ValidatePtx89(".version 8.7\n.target sm_89\n") ||
        RetargetPtx89To86(".version 8.7\n.target sm_89\n") != ".version 8.7\n.target sm_86\n" ||
        ValidatePtx89(".target sm_75\n") || !ValidateMixedFatbinOrder(true, true, true) ||
        !ampere_provider::memory::IsReadableProtection(PAGE_READONLY) ||
        !ampere_provider::memory::IsReadableProtection(PAGE_READWRITE) ||
        !ampere_provider::memory::IsReadableProtection(PAGE_EXECUTE_READ) ||
        !ampere_provider::memory::IsReadableProtection(PAGE_EXECUTE_READWRITE) ||
        ampere_provider::memory::IsReadableProtection(PAGE_NOACCESS) ||
        ampere_provider::memory::IsReadableProtection(PAGE_READONLY | PAGE_GUARD) ||
        ampere_provider::memory::IsReadableProtection(PAGE_READONLY | PAGE_NOCACHE) == false ||
        ampere_provider::memory::RegionCovers(0x1100, 0x1000, 0x1000, 0x100) == false ||
        ampere_provider::memory::RegionCovers(0x1F00, 0x1000, 0x1000, 0x200)) return 1;
    Stage("SELFTEST_COMPLETE");
    return 0;
}

int RunArchPreflight() {
    ampere_bridge::Bridge bridge;
    std::string detail;
    HMODULE shim = nullptr;
    IDXGIFactory6* factory = nullptr;
    IDXGIAdapter1* selected = nullptr;
    int result = 40;
    Stage("NVAPI_SHIM_LOAD_STARTED");
    if (!bridge.Initialize(detail)) { Log("ARCH_PREFLIGHT_FAILED: %s", detail.c_str()); goto cleanup; }
    shim = GetModuleHandleW(L"nvapi64.dll");
    if (!shim) { Log("ARCH_PREFLIGHT_FAILED: NVAPI shim handle unavailable"); goto cleanup; }
    Stage("NVAPI_SHIM_LOADED");
    {
        auto query = reinterpret_cast<ampere_bridge::NvQueryInterface>(GetProcAddress(shim, "nvapi_QueryInterface"));
        auto target = query ? query(0xD8265D24u) : nullptr;
        if (!query || !target) { Log("ARCH_PREFLIGHT_FAILED: QueryInterface resolution failed"); goto cleanup; }
        Stage("NVAPI_QUERY_INTERFACE_RESOLVED");
        HMODULE owner = nullptr; MODULEINFO info{};
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS, reinterpret_cast<LPCWSTR>(target), &owner) ||
            !GetModuleInformation(GetCurrentProcess(), owner, &info, sizeof(info))) {
            Log("ARCH_PREFLIGHT_FAILED: target owner resolution failed"); goto cleanup;
        }
        wchar_t owner_path[32768]{}; const DWORD owner_len = GetModuleFileNameW(owner, owner_path, ARRAYSIZE(owner_path));
        const auto rva = reinterpret_cast<const uint8_t*>(target) - reinterpret_cast<const uint8_t*>(info.lpBaseOfDll);
        std::array<uint8_t, 20> prologue{}; memcpy(prologue.data(), target, prologue.size());
        std::fprintf(stderr, "NVAPI_TARGET_OWNER=%ls\nNVAPI_TARGET_RVA=0x%zX\nNVAPI_TARGET_PROLOGUE=", owner_len ? owner_path : L"<unavailable>", rva);
        for (uint8_t byte : prologue) std::fprintf(stderr, "%02X", byte);
        std::fprintf(stderr, "\n"); std::fflush(stderr);
    }
    if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) { Log("ARCH_PREFLIGHT_FAILED: DXGI factory creation failed"); goto cleanup; }
    for (UINT i = 0; factory->EnumAdapterByGpuPreference(i, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&selected)) != DXGI_ERROR_NOT_FOUND; ++i) {
        DXGI_ADAPTER_DESC1 desc{}; if (FAILED(selected->GetDesc1(&desc))) { selected->Release(); selected = nullptr; continue; }
        if (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) { selected->Release(); selected = nullptr; continue; }
        if (desc.VendorId == 0x10DE) { Log("GPU_HANDLE_RESOLVED"); break; }
        selected->Release(); selected = nullptr;
    }
    if (!selected) { Log("ARCH_PREFLIGHT_FAILED: NVIDIA DXGI adapter not found"); goto cleanup; }
    if (!bridge.BindAdapter(selected, detail)) { Log("ARCH_PREFLIGHT_FAILED: %s", detail.c_str()); goto cleanup; }
    Log("GPU_VENDOR_ID=0x10DE");
    Log("GPU_NATIVE_ARCH=0x%X", bridge.binding().native_architecture.architecture);
    Log("GPU_IMPLEMENTATION=0x%X", bridge.binding().native_architecture.implementation);
    Stage("ARCH_PROFILE=Ampere");
    Stage("ARCH_TARGET_SM=86");
    Log("ARCH_EXPOSED_VALUE=0x%X", ampere_provider::kAdaArchitecture);
    {
        ampere_bridge::NvGpuArchInfo before{}; const auto native_status = bridge.QueryNative(&before);
        if (native_status != NVAPI_OK || before.architecture != ampere_provider::kNativeArchitecture) {
            Log("ARCH_PREFLIGHT_FAILED: native architecture value/status mismatch status=0x%X value=0x%X", native_status, before.architecture); goto cleanup;
        }
        Log("ARCH_NATIVE_BEFORE=0x%X", before.architecture);
        Stage("ARCH_BRIDGE_INSTALL_STARTED");
        if (!bridge.PrepareArchitecturePreflight(detail)) { Log("ARCH_BRIDGE_INSTALL_RESULT=0 detail=%s", detail.c_str()); goto cleanup; }
        Stage("ARCH_BRIDGE_INSTALL_RESULT=1");
        ampere_bridge::NvGpuArchInfo bridged{}; const auto bridged_status = bridge.QueryBridged(&bridged);
        Log("ARCH_BRIDGE_HOOK_CALLS=%u", bridge.HookCallCountForTest());
        if (bridged_status != NVAPI_OK || bridged.architecture != ampere_provider::kAdaArchitecture ||
            bridged.implementation != before.implementation || bridged.revision != before.revision) {
            Log("ARCH_PREFLIGHT_FAILED: bridged result/status or unrelated fields mismatch status=0x%X value=0x%X implementation=0x%X revision=0x%X", bridged_status, bridged.architecture, bridged.implementation, bridged.revision); goto cleanup;
        }
        Log("ARCH_BRIDGED=0x%X", bridged.architecture);
        const bool removed = bridge.RemoveArchitecturePreflight();
        Log("ARCH_BRIDGE_REMOVE_RESULT=%d", removed ? 1 : 0);
        ampere_bridge::NvGpuArchInfo after{}; const auto after_status = bridge.QueryNative(&after);
        Log("ARCH_NATIVE_AFTER=0x%X", after.architecture);
        if (!removed || after_status != NVAPI_OK || after.architecture != ampere_provider::kNativeArchitecture || memcmp(&after, &before, sizeof(after)) != 0) { Log("ARCH_PREFLIGHT_FAILED: native restoration verification failed"); goto cleanup; }
    }
    Stage("ARCH_BRIDGE_READY");
    result = 0;
cleanup:
    if (selected) selected->Release();
    if (factory) factory->Release();
    bridge.Shutdown();
    return result;
}

int RunProviderPreflight(const wchar_t* provider_path) {
    ampere_provider::Session read_only;
    Stage("PROVIDER_IDENTITY_OK");
    Stage("PROVIDER_LOAD_STARTED");
    std::string detail;
    size_t planned_edits = 0, hidden_cubins = 0;
    if (!read_only.InspectOnly(provider_path, detail, planned_edits, hidden_cubins)) {
        Log("PROVIDER_PREFLIGHT_FAILED: %s", detail.c_str());
        return 30;
    }
    HMODULE module = read_only.module();
    MODULEINFO info{};
    MEMORY_BASIC_INFORMATION vq{};
    wchar_t path[32768] = {};
    const DWORD path_length = GetModuleFileNameW(module, path, ARRAYSIZE(path));
    if (!GetModuleInformation(GetCurrentProcess(), module, &info, sizeof(info)) ||
        VirtualQuery(module, &vq, sizeof(vq)) != sizeof(vq) || path_length == 0) {
        Log("PROVIDER_PREFLIGHT_FAILED: module diagnostics unavailable");
        return 31;
    }
    Log("PROVIDER_LOADED");
    Log("PROVIDER_HANDLE=0x%p", module);
    Log("PROVIDER_BASE=0x%p", info.lpBaseOfDll);
    Log("GETMODULEFILENAME=%ls", path);
    Log("VQ_BASE_ADDRESS=0x%p", vq.BaseAddress);
    Log("VQ_ALLOCATION_BASE=0x%p", vq.AllocationBase);
    Log("VQ_ALLOCATION_PROTECT=0x%08X", vq.AllocationProtect);
    Log("VQ_REGION_SIZE=%zu", static_cast<size_t>(vq.RegionSize));
    Log("VQ_STATE=0x%08X", vq.State);
    Log("VQ_PROTECT=0x%08X", vq.Protect);
    Log("VQ_TYPE=0x%08X", vq.Type);
    Log("DOS_POINTER=0x%p", module);
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(module);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(
        reinterpret_cast<const uint8_t*>(module) + dos->e_lfanew);
    Log("PE_MZ=0x%04X PE_SIGNATURE=0x%08X PE_MAGIC=0x%04X SIZE_OF_IMAGE=%u",
        dos->e_magic, nt->Signature, nt->OptionalHeader.Magic,
        nt->OptionalHeader.SizeOfImage);
    if (info.lpBaseOfDll != reinterpret_cast<LPVOID>(module) ||
        dos->e_magic != IMAGE_DOS_SIGNATURE || nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
        Log("PROVIDER_HEADERS_FAILED: module identity or PE headers mismatch");
        return 32;
    }
    Stage("PROVIDER_HEADERS_OK");
    Stage("PROVIDER_STRUCTURE_SCAN_STARTED");
    Log("PROVIDER_EDIT_PLAN_READY edits=%zu hidden_cubins=%zu provider_arch_gate_count=%zu", planned_edits, hidden_cubins, read_only.provider_arch_gate_count());
    Stage("PROVIDER_STRUCTURE_SCAN_OK");
    if (!read_only.Unload()) {
        Log("PROVIDER_UNLOAD_RESULT=0");
        return 33;
    }
    Log("PROVIDER_UNLOAD_RESULT=1");
    Stage("PROVIDER_PREFLIGHT_COMPLETE");

    ampere_provider::Session apply;
    Stage("PROVIDER_APPLY_STARTED");
    if (!apply.LoadAndAdapt(provider_path, detail)) {
        Log("PROVIDER_APPLY_RESULT=0 detail=%s", detail.c_str());
        return 34;
    }
    Log("PROVIDER_APPLY_RESULT=1");
    const bool verified = apply.VerifyReadback(detail);
    Log("PROVIDER_VERIFY_RESULT=%d", verified ? 1 : 0);
    if (!verified) return 35;
    Stage("PROVIDER_ROLLBACK_STARTED");
    const bool rolled_back = apply.Rollback();
    Log("PROVIDER_ROLLBACK_RESULT=%d", rolled_back ? 1 : 0);
    const bool restored = rolled_back && apply.Restored();
    Log("PROVIDER_POSTROLLBACK_VERIFY=%d", restored ? 1 : 0);
    if (!restored) return 36;
    const bool unloaded = apply.Unload();
    Log("PROVIDER_UNLOAD_RESULT=%d", unloaded ? 1 : 0);
    if (!unloaded) return 37;
    Stage("PROVIDER_PREFLIGHT_COMPLETE");
    return 0;
}

int Run2x(const wchar_t* provider_path) {
    Worker worker;
    if (!worker.Initialize(nullptr, provider_path)) return 20;
    if (!worker.available() || worker.maximum() < 1) return 21;
    if (!worker.CreateFeature(256, 256, 1)) return 22;
    auto frame_a = MakeColor(64), frame_b = MakeColor(72), zero_mv = MakeMotion(0.0f, 0.0f), moving_mv = MakeMotion(-8.0f, 0.0f);
    std::vector<std::vector<uint8_t>> outputs; bool disabled = false;
    if (!worker.Upload(frame_a.data(), zero_mv.data()) || NVSDK_NGX_FAILED(worker.EvaluateGroup(0, true, outputs, disabled))) return 23;
    outputs.clear(); disabled = false;
    if (!worker.Upload(frame_b.data(), moving_mv.data()) || NVSDK_NGX_FAILED(worker.EvaluateGroup(1, false, outputs, disabled))) return 24;
    if (outputs.size() != 1 || outputs[0].empty() || disabled) return 25;
    const auto digest = Sha256(outputs[0]);
    Log("OUTPUT_SHA256=%s", digest.c_str());
    Log("OUTPUT_BYTES=%zu", outputs[0].size());
    bool all_zero = true, constant = true;
    for (size_t i = 0; i < outputs[0].size(); ++i) { all_zero &= outputs[0][i] == 0; if (i && outputs[0][i] != outputs[0][0]) constant = false; }
    Log("OUTPUT_ALL_ZERO=%d", all_zero ? 1 : 0);
    Log("OUTPUT_CONSTANT=%d", constant ? 1 : 0);
    return 0;
}

int main(int argc, char** argv) {
    Stage("PROCESS_ENTRY");
    if (argc == 2 && strcmp(argv[1], "--selftest") == 0) { Stage("ARGS_PARSED"); return SelfTest(); }
    if (argc == 2 && strcmp(argv[1], "--arch-preflight") == 0) { Stage("ARGS_PARSED"); const int result = RunArchPreflight(); Log("CLEANUP_COMPLETE"); return result; }
    if (argc == 4 && strcmp(argv[1], "--provider-preflight") == 0 && strcmp(argv[2], "--provider") == 0) {
        Stage("ARGS_PARSED");
        std::wstring provider(argv[3], argv[3] + strlen(argv[3]));
        const int result = RunProviderPreflight(provider.c_str());
        Log("CLEANUP_COMPLETE");
        return result;
    }
    if (argc == 4 && strcmp(argv[1], "--run-2x") == 0 && strcmp(argv[2], "--provider") == 0) {
        Stage("ARGS_PARSED");
        std::wstring provider(argv[3], argv[3] + strlen(argv[3]));
        const int result = Run2x(provider.c_str());
        Log("CLEANUP_COMPLETE");
        return result;
    }
    Stage("ARGS_PARSED");
    Log("usage: dlssg_ampere_reference.exe --selftest | --run-2x --provider <path>");
    return 2;
}
