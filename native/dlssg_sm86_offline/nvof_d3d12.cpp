#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <nvOpticalFlowD3D12.h>

#include "nvof_d3d12.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <limits>
#include <numeric>
#include <vector>

namespace {

using GetMaxVersionFn = NV_OF_STATUS(NVOFAPI *)(uint32_t *);
using CreateInstanceFn = NV_OF_STATUS(NVOFAPI *)(uint32_t, NV_OF_D3D12_API_FUNCTION_LIST *);
using Clock = std::chrono::steady_clock;

void Log(const char *format, ...) {
    va_list args;
    va_start(args, format);
    std::vfprintf(stderr, format, args);
    va_end(args);
    std::fputc('\n', stderr);
    std::fflush(stderr);
}

template <class T> void Release(T *&value) {
    if (value) {
        value->Release();
        value = nullptr;
    }
}

bool QueryValues(NV_OF_D3D12_API_FUNCTION_LIST &api, NvOFHandle handle, NV_OF_CAPS cap,
    std::vector<uint32_t> &values) {
    uint32_t count = 0;
    if (api.nvOFGetCaps(handle, cap, nullptr, &count) != NV_OF_SUCCESS || count == 0) return false;
    values.resize(count);
    return api.nvOFGetCaps(handle, cap, values.data(), &count) == NV_OF_SUCCESS;
}

bool QueryFormats(NV_OF_D3D12_API_FUNCTION_LIST &api, NvOFHandle handle, NV_OF_BUFFER_USAGE usage,
    std::vector<DXGI_FORMAT> &formats) {
    uint32_t count = 0;
    if (api.nvOFGetSurfaceFormatCountD3D12(handle, usage, NV_OF_MODE_OPTICALFLOW, &count) != NV_OF_SUCCESS || count == 0) return false;
    formats.resize(count);
    return api.nvOFGetSurfaceFormatD3D12(handle, usage, NV_OF_MODE_OPTICALFLOW, formats.data()) == NV_OF_SUCCESS;
}

void LogFormats(const char *name, const std::vector<DXGI_FORMAT> &formats) {
    std::fprintf(stderr, "%s=", name);
    for (size_t index = 0; index < formats.size(); ++index) {
        std::fprintf(stderr, "%s%u", index ? "," : "", static_cast<unsigned>(formats[index]));
    }
    std::fputc('\n', stderr);
    std::fflush(stderr);
}

double Milliseconds(Clock::time_point begin, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - begin).count();
}

ID3D12Resource *CreateTexture(ID3D12Device *device, uint32_t width, uint32_t height,
    DXGI_FORMAT format, D3D12_RESOURCE_STATES initialState) {
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = width;
    desc.Height = height;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.Format = format;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    ID3D12Resource *resource = nullptr;
    return SUCCEEDED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
        initialState, nullptr, IID_PPV_ARGS(&resource))) ? resource : nullptr;
}

ID3D12Resource *CreateBuffer(ID3D12Device *device, uint64_t bytes, D3D12_HEAP_TYPE type,
    D3D12_RESOURCE_STATES initialState) {
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = type;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = bytes;
    desc.Height = 1;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ID3D12Resource *resource = nullptr;
    return SUCCEEDED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
        initialState, nullptr, IID_PPV_ARGS(&resource))) ? resource : nullptr;
}

void Transition(ID3D12GraphicsCommandList *list, ID3D12Resource *resource,
    D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
    if (before == after) return;
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = resource;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = before;
    barrier.Transition.StateAfter = after;
    list->ResourceBarrier(1, &barrier);
}

bool WaitFence(ID3D12Fence *fence, uint64_t value, HANDLE eventHandle) {
    if (fence->GetCompletedValue() >= value) return true;
    return SUCCEEDED(fence->SetEventOnCompletion(value, eventHandle)) &&
        WaitForSingleObject(eventHandle, 15000) == WAIT_OBJECT_0;
}

uint16_t FloatToHalf(float value) {
    uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    const uint32_t sign = (bits >> 16) & 0x8000u;
    const uint32_t exponent = (bits >> 23) & 0xffu;
    uint32_t mantissa = bits & 0x7fffffu;
    if (exponent == 255) return static_cast<uint16_t>(sign | 0x7c00u | (mantissa ? 0x200u : 0));
    const int adjusted = static_cast<int>(exponent) - 127 + 15;
    if (adjusted >= 31) return static_cast<uint16_t>(sign | 0x7c00u);
    if (adjusted <= 0) {
        if (adjusted < -10) return static_cast<uint16_t>(sign);
        mantissa |= 0x800000u;
        return static_cast<uint16_t>(sign | (mantissa >> (14 - adjusted)));
    }
    return static_cast<uint16_t>(sign | (static_cast<uint32_t>(adjusted) << 10) | (mantissa >> 13));
}

} // namespace

struct NvofD3D12::Impl {
    HMODULE module = nullptr;
    NV_OF_D3D12_API_FUNCTION_LIST api{};
    NvOFHandle handle = nullptr;
    ID3D12Device *device = nullptr;
    ID3D12CommandQueue *queue = nullptr;
    ID3D12CommandAllocator *allocator = nullptr;
    ID3D12GraphicsCommandList *list = nullptr;
    ID3D12Fence *queueFence = nullptr;
    ID3D12Fence *ofFence = nullptr;
    HANDLE eventHandle = nullptr;
    uint64_t queueFenceValue = 0;
    uint64_t ofFenceValue = 0;
    bool forwardOnly = false;
    uint32_t width = 0;
    uint32_t height = 0;
    ID3D12Resource *previous = nullptr;
    ID3D12Resource *current = nullptr;
    ID3D12Resource *forward = nullptr;
    ID3D12Resource *backward = nullptr;
    ID3D12Resource *previousUpload = nullptr;
    ID3D12Resource *currentUpload = nullptr;
    ID3D12Resource *backwardReadback = nullptr;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT inputFootprint{};
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT outputFootprint{};
    uint64_t inputBytes = 0;
    uint64_t outputBytes = 0;
    NvOFGPUBufferHandle previousHandle = nullptr;
    NvOFGPUBufferHandle currentHandle = nullptr;
    NvOFGPUBufferHandle forwardHandle = nullptr;
    NvOFGPUBufferHandle backwardHandle = nullptr;

    bool ResetList() {
        return SUCCEEDED(allocator->Reset()) && SUCCEEDED(list->Reset(allocator, nullptr));
    }

    bool SubmitAndWait() {
        if (FAILED(list->Close())) return false;
        ID3D12CommandList *commands[] = {list};
        queue->ExecuteCommandLists(1, commands);
        const uint64_t value = ++queueFenceValue;
        return SUCCEEDED(queue->Signal(queueFence, value)) && WaitFence(queueFence, value, eventHandle);
    }

    bool Register(ID3D12Resource *resource, NvOFGPUBufferHandle &gpuHandle) {
        NV_OF_REGISTER_RESOURCE_PARAMS_D3D12 params{};
        params.resource = resource;
        params.inputFencePoint = {ofFence, ofFence->GetCompletedValue()};
        params.hOFGpuBuffer = &gpuHandle;
        params.outputFencePoint = {ofFence, ++ofFenceValue};
        const NV_OF_STATUS status = api.nvOFRegisterResourceD3D12(handle, &params);
        return status == NV_OF_SUCCESS && gpuHandle && WaitFence(ofFence, ofFenceValue, eventHandle);
    }

    bool MapUpload(ID3D12Resource *upload, const uint8_t *rgba) {
        uint8_t *mapped = nullptr;
        if (FAILED(upload->Map(0, nullptr, reinterpret_cast<void **>(&mapped)))) return false;
        for (uint32_t y = 0; y < height; ++y) {
            uint8_t *dst = mapped + static_cast<size_t>(y) * inputFootprint.Footprint.RowPitch;
            const uint8_t *src = rgba + static_cast<size_t>(y) * width * 4;
            for (uint32_t x = 0; x < width; ++x) {
                dst[x * 4 + 0] = src[x * 4 + 2];
                dst[x * 4 + 1] = src[x * 4 + 1];
                dst[x * 4 + 2] = src[x * 4 + 0];
                dst[x * 4 + 3] = src[x * 4 + 3];
            }
        }
        upload->Unmap(0, nullptr);
        return true;
    }

    void RecordUpload(ID3D12Resource *upload, ID3D12Resource *texture) {
        Transition(list, texture, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION source{}, destination{};
        source.pResource = upload;
        source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        source.PlacedFootprint = inputFootprint;
        destination.pResource = texture;
        destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
        Transition(list, texture, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COMMON);
    }

    bool Upload(ID3D12Resource *upload, ID3D12Resource *texture, const uint8_t *rgba) {
        if (!MapUpload(upload, rgba) || !ResetList()) return false;
        RecordUpload(upload, texture);
        return SubmitAndWait();
    }

    bool ReadFlow(ID3D12Resource *flow, std::vector<NV_OF_FLOW_VECTOR> &raw) {
        if (!ResetList()) return false;
        Transition(list, flow, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION source{}, destination{};
        source.pResource = flow;
        source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        destination.pResource = backwardReadback;
        destination.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        destination.PlacedFootprint = outputFootprint;
        list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
        Transition(list, flow, D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_COMMON);
        if (!SubmitAndWait()) return false;
        uint8_t *mapped = nullptr;
        if (FAILED(backwardReadback->Map(0, nullptr, reinterpret_cast<void **>(&mapped)))) return false;
        raw.resize(static_cast<size_t>(width) * height);
        for (uint32_t y = 0; y < height; ++y) {
            std::memcpy(raw.data() + static_cast<size_t>(y) * width,
                mapped + static_cast<size_t>(y) * outputFootprint.Footprint.RowPitch,
                static_cast<size_t>(width) * sizeof(NV_OF_FLOW_VECTOR));
        }
        backwardReadback->Unmap(0, nullptr);
        return true;
    }
};

NvofD3D12::NvofD3D12() : impl_(new Impl{}) {}
NvofD3D12::~NvofD3D12() { Shutdown(); delete impl_; }

bool NvofD3D12::Initialize(ID3D12Device *device, ID3D12CommandQueue *queue, uint32_t width, uint32_t height) {
    Shutdown();
    if (!device || !queue || !width || !height) return false;
    auto &state = *impl_;
    state.width = width;
    state.height = height;
    state.device = device;
    state.queue = queue;
    state.device->AddRef();
    state.queue->AddRef();
    state.module = LoadLibraryExW(L"nvofapi64.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!state.module) return false;
    Log("NVOF_MODULE_LOADED");
    auto getMax = reinterpret_cast<GetMaxVersionFn>(GetProcAddress(state.module, "NvOFGetMaxSupportedApiVersion"));
    auto createInstance = reinterpret_cast<CreateInstanceFn>(GetProcAddress(state.module, "NvOFAPICreateInstanceD3D12"));
    uint32_t driverVersion = 0;
    if (!getMax || !createInstance || getMax(&driverVersion) != NV_OF_SUCCESS || driverVersion < NV_OF_API_VERSION) return false;
    Log("NVOF_API_VERSION_DRIVER=0x%X", driverVersion);
    Log("NVOF_API_VERSION_CLIENT=0x%X", static_cast<unsigned>(NV_OF_API_VERSION));
    if (createInstance(NV_OF_API_VERSION, &state.api) != NV_OF_SUCCESS ||
        state.api.nvCreateOpticalFlowD3D12(device, &state.handle) != NV_OF_SUCCESS || !state.handle) return false;
    Log("NVOF_INSTANCE_CREATED");

    std::vector<uint32_t> grids;
    std::vector<DXGI_FORMAT> inputs;
    std::vector<DXGI_FORMAT> outputs;
    if (!QueryValues(state.api, state.handle, NV_OF_CAPS_SUPPORTED_OUTPUT_GRID_SIZES, grids) ||
        std::find(grids.begin(), grids.end(), static_cast<uint32_t>(NV_OF_OUTPUT_VECTOR_GRID_SIZE_1)) == grids.end() ||
        !QueryFormats(state.api, state.handle, NV_OF_BUFFER_USAGE_INPUT, inputs) ||
        std::find(inputs.begin(), inputs.end(), DXGI_FORMAT_B8G8R8A8_UNORM) == inputs.end() ||
        !QueryFormats(state.api, state.handle, NV_OF_BUFFER_USAGE_OUTPUT, outputs) ||
        std::find(outputs.begin(), outputs.end(), DXGI_FORMAT_R16G16_SINT) == outputs.end()) return false;
    Log("NVOF_GRID_1X1_SUPPORTED=1");

    NV_OF_INIT_PARAMS init{};
    init.width = width;
    init.height = height;
    init.outGridSize = NV_OF_OUTPUT_VECTOR_GRID_SIZE_1;
    init.mode = NV_OF_MODE_OPTICALFLOW;
    // The production video path is throughput-bound by NVOF at 720p/1080p.
    // HIGH is the SDK-supported performance tier; it does not alter the
    // flow direction, format, or temporal-hint contract.
    init.perfLevel = NV_OF_PERF_LEVEL_FAST;
    wchar_t direction[32]{};
    state.forwardOnly = GetEnvironmentVariableW(L"DLSSG_NVOF_DIRECTION", direction, static_cast<DWORD>(std::size(direction))) != 0 &&
        _wcsicmp(direction, L"forward") == 0;
    init.predDirection = state.forwardOnly ? NV_OF_PRED_DIRECTION_FORWARD : NV_OF_PRED_DIRECTION_BOTH;
    init.inputBufferFormat = NV_OF_BUFFER_FORMAT_ABGR8;
    if (state.api.nvOFInit(state.handle, &init) != NV_OF_SUCCESS) return false;
    Log("NVOF_DIRECTION_MODE=%s", state.forwardOnly ? "FORWARD" : "BOTH");

    D3D12_COMMAND_QUEUE_DESC queueDesc{};
    if (FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&state.allocator))) ||
        FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, state.allocator, nullptr, IID_PPV_ARGS(&state.list))) ||
        FAILED(state.list->Close()) ||
        FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&state.queueFence))) ||
        FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&state.ofFence)))) return false;
    state.eventHandle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!state.eventHandle) return false;

    state.previous = CreateTexture(device, width, height, DXGI_FORMAT_B8G8R8A8_UNORM, D3D12_RESOURCE_STATE_COMMON);
    state.current = CreateTexture(device, width, height, DXGI_FORMAT_B8G8R8A8_UNORM, D3D12_RESOURCE_STATE_COMMON);
    state.forward = CreateTexture(device, width, height, DXGI_FORMAT_R16G16_SINT, D3D12_RESOURCE_STATE_COMMON);
    state.backward = CreateTexture(device, width, height, DXGI_FORMAT_R16G16_SINT, D3D12_RESOURCE_STATE_COMMON);
    if (!state.previous || !state.current || !state.forward || !state.backward) return false;
    const auto inputDesc = state.previous->GetDesc();
    const auto outputDesc = state.backward->GetDesc();
    device->GetCopyableFootprints(&inputDesc, 0, 1, 0, &state.inputFootprint, nullptr, nullptr, &state.inputBytes);
    device->GetCopyableFootprints(&outputDesc, 0, 1, 0, &state.outputFootprint, nullptr, nullptr, &state.outputBytes);
    state.previousUpload = CreateBuffer(device, state.inputBytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    state.currentUpload = CreateBuffer(device, state.inputBytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    state.backwardReadback = CreateBuffer(device, state.outputBytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    if (!state.previousUpload || !state.currentUpload || !state.backwardReadback) return false;
    if (!state.Register(state.previous, state.previousHandle) || !state.Register(state.current, state.currentHandle) ||
        !state.Register(state.forward, state.forwardHandle) || !state.Register(state.backward, state.backwardHandle)) return false;
    Log("NVOF_RESOURCES_REGISTERED width=%u height=%u inputFormat=%u outputFormat=%u", width, height,
        static_cast<unsigned>(DXGI_FORMAT_B8G8R8A8_UNORM), static_cast<unsigned>(DXGI_FORMAT_R16G16_SINT));
    return true;
}

bool NvofD3D12::ComputeBackward(const uint8_t *previousRgba, const uint8_t *currentRgba,
    bool resetTemporalHints, std::vector<uint8_t> &motionR16G16Float,
    std::vector<NvofFlowVector> *flowPixels, NvofFlowStatistics *statistics, NvofTimings *timings) {
    if (!impl_->handle || !previousRgba || !currentRgba) return false;
    auto &state = *impl_;
    NvofTimings measured{};
    const auto uploadStart = Clock::now();
    if (!state.MapUpload(state.previousUpload, previousRgba) ||
        !state.MapUpload(state.currentUpload, currentRgba) || !state.ResetList()) return false;
    state.RecordUpload(state.previousUpload, state.previous);
    state.RecordUpload(state.currentUpload, state.current);
    if (!state.SubmitAndWait()) return false;
    const auto uploadEnd = Clock::now();
    NV_OF_FENCE_POINT inputFence{state.queueFence, state.queueFenceValue};
    NV_OF_FENCE_POINT outputFence{state.ofFence, ++state.ofFenceValue};
    NV_OF_EXECUTE_INPUT_PARAMS_D3D12 input{};
    input.inputFrame = state.forwardOnly ? state.currentHandle : state.previousHandle;
    input.referenceFrame = state.forwardOnly ? state.previousHandle : state.currentHandle;
    input.disableTemporalHints = resetTemporalHints ? NV_OF_TRUE : NV_OF_FALSE;
    input.numFencePoints = 1;
    input.fencePoint = &inputFence;
    NV_OF_EXECUTE_OUTPUT_PARAMS_D3D12 output{};
    output.outputBuffer = state.forwardHandle;
    output.bwdOutputBuffer = state.forwardOnly ? nullptr : state.backwardHandle;
    output.fencePoint = &outputFence;
    const auto executeStart = Clock::now();
    const NV_OF_STATUS executeStatus = state.api.nvOFExecuteD3D12(state.handle, &input, &output);
    if (executeStatus != NV_OF_SUCCESS || !WaitFence(state.ofFence, state.ofFenceValue, state.eventHandle)) {
        Log("NVOF_EXECUTE_FAILED status=%d", static_cast<int>(executeStatus));
        return false;
    }
    const auto executeEnd = Clock::now();
    std::vector<NV_OF_FLOW_VECTOR> raw;
    const auto readbackStart = Clock::now();
    if (!state.ReadFlow(state.forwardOnly ? state.forward : state.backward, raw)) return false;
    const auto readbackEnd = Clock::now();
    const auto conversionStart = Clock::now();
    motionR16G16Float.resize(raw.size() * 4);
    if (flowPixels) flowPixels->resize(raw.size());
    std::vector<float> xSamples;
    std::vector<float> ySamples;
    std::vector<float> magnitudeSamples;
    const size_t maximumStatisticSamples = 65536;
    const size_t sampleStride = statistics
        ? std::max<size_t>(1, (raw.size() + maximumStatisticSamples - 1) / maximumStatisticSamples)
        : 1;
    double sumX = 0.0;
    double sumY = 0.0;
    double sumMagnitude = 0.0;
    double sumSquaredMagnitude = 0.0;
    double maximumMagnitude = 0.0;
    size_t nearZero = 0;
    size_t unusuallyLarge = 0;
    const double largeThreshold = std::max(state.width, state.height) * 0.25;
    if (statistics) {
        const size_t sampleCapacity = (raw.size() + sampleStride - 1) / sampleStride;
        xSamples.reserve(sampleCapacity);
        ySamples.reserve(sampleCapacity);
        magnitudeSamples.reserve(sampleCapacity);
    }
    for (size_t index = 0; index < raw.size(); ++index) {
        const float x = static_cast<float>(raw[index].flowx) / 32.0f;
        const float y = static_cast<float>(raw[index].flowy) / 32.0f;
        const uint16_t hx = FloatToHalf(x);
        const uint16_t hy = FloatToHalf(y);
        std::memcpy(motionR16G16Float.data() + index * 4, &hx, 2);
        std::memcpy(motionR16G16Float.data() + index * 4 + 2, &hy, 2);
        if (flowPixels) (*flowPixels)[index] = {x, y};
        if (statistics) {
            const double magnitude = std::sqrt(static_cast<double>(x) * x + static_cast<double>(y) * y);
            sumX += x;
            sumY += y;
            sumMagnitude += magnitude;
            sumSquaredMagnitude += magnitude * magnitude;
            maximumMagnitude = std::max(maximumMagnitude, magnitude);
            nearZero += magnitude <= 0.5 ? 1u : 0u;
            unusuallyLarge += magnitude > largeThreshold ? 1u : 0u;
            if (index % sampleStride == 0) {
                xSamples.push_back(x);
                ySamples.push_back(y);
                magnitudeSamples.push_back(static_cast<float>(magnitude));
            }
        }
    }
    if (statistics && !raw.empty()) {
        NvofFlowStatistics summary{};
        const double count = static_cast<double>(raw.size());
        summary.meanX = sumX / count;
        summary.meanY = sumY / count;
        const auto percentile = [](std::vector<float> values, double fraction) {
            const size_t index = std::min(values.size() - 1,
                static_cast<size_t>(std::ceil(fraction * values.size()) - 1));
            std::nth_element(values.begin(), values.begin() + index, values.end());
            return static_cast<double>(values[index]);
        };
        summary.medianX = percentile(xSamples, 0.5);
        summary.medianY = percentile(ySamples, 0.5);
        summary.p95Magnitude = percentile(magnitudeSamples, 0.95);
        summary.maximumMagnitude = maximumMagnitude;
        const double meanMagnitude = sumMagnitude / count;
        const double variance = std::max(0.0, sumSquaredMagnitude / count - meanMagnitude * meanMagnitude);
        summary.standardDeviationMagnitude = std::sqrt(variance);
        summary.nearZeroPercent = 100.0 * nearZero / count;
        summary.unusuallyLargePercent = 100.0 * unusuallyLarge / count;
        *statistics = summary;
    }
    const auto conversionEnd = Clock::now();
    measured.uploadMs = Milliseconds(uploadStart, uploadEnd);
    measured.executeMs = Milliseconds(executeStart, executeEnd);
    measured.readbackMs = Milliseconds(readbackStart, readbackEnd);
    measured.conversionMs = Milliseconds(conversionStart, conversionEnd);
    if (timings) *timings = measured;
    Log("NVOF_EXECUTE_COMPLETE direction=%s uploadMs=%.3f executeMs=%.3f readbackMs=%.3f conversionMs=%.3f",
        state.forwardOnly ? "FORWARD_CURRENT_TO_PREVIOUS" : "BACKWARD_CURRENT_TO_PREVIOUS",
        measured.uploadMs, measured.executeMs, measured.readbackMs, measured.conversionMs);
    return true;
}

void NvofD3D12::Shutdown() {
    if (!impl_) return;
    auto &state = *impl_;
    if (!state.handle && !state.module) return;
    Log("NVOF_SHUTDOWN_STARTED handle=%p", static_cast<void *>(state.handle));
    const std::array<NvOFGPUBufferHandle *, 4> handles = {
        &state.previousHandle, &state.currentHandle, &state.forwardHandle, &state.backwardHandle};
    uint32_t unregistered = 0;
    bool unregisterOk = true;
    if (state.api.nvOFUnregisterResourceD3D12) {
        for (auto *entry : handles) {
            if (*entry) {
                NV_OF_UNREGISTER_RESOURCE_PARAMS_D3D12 params{*entry};
                const NV_OF_STATUS status = state.api.nvOFUnregisterResourceD3D12(&params);
                unregisterOk &= status == NV_OF_SUCCESS;
                ++unregistered;
                *entry = nullptr;
            }
        }
    }
    Log("NVOF_UNREGISTER_RESULT count=%u success=%d", unregistered, unregisterOk ? 1 : 0);
    // Keep the OF session alive while the application releases resources that
    // were registered with it. Driver 610.62 faults if the session is destroyed
    // first and the final ID3D12Resource references are released afterwards.
    Release(state.previous);
    Release(state.current);
    Release(state.forward);
    Release(state.backward);
    Release(state.previousUpload);
    Release(state.currentUpload);
    Release(state.backwardReadback);
    if (state.handle && state.api.nvOFDestroy) {
        Log("NVOF_DESTROY_STARTED handle=%p", static_cast<void *>(state.handle));
        const NV_OF_STATUS status = state.api.nvOFDestroy(state.handle);
        Log("NVOF_DESTROY_RESULT=%d", static_cast<int>(status));
    }
    state.handle = nullptr;
    Release(state.list);
    Release(state.allocator);
    Release(state.queueFence);
    Release(state.ofFence);
    Release(state.queue);
    Release(state.device);
    if (state.eventHandle) CloseHandle(state.eventHandle);
    state.eventHandle = nullptr;
    if (state.module) FreeLibrary(state.module);
    state.module = nullptr;
    state.api = {};
    state.width = state.height = 0;
    state.queueFenceValue = state.ofFenceValue = 0;
    Log("NVOF_SHUTDOWN_COMPLETE");
}

uint32_t NvofD3D12::Width() const { return impl_->width; }
uint32_t NvofD3D12::Height() const { return impl_->height; }

int RunNvofProbe() {
    Log("PROCESS_ENTRY");
    Log("ARGS_PARSED");
    HMODULE module = LoadLibraryExW(L"nvofapi64.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module) {
        Log("NVOF_MODULE_LOAD_FAILED winerr=%lu", GetLastError());
        return 80;
    }
    Log("NVOF_MODULE_LOADED path=C:\\Windows\\System32\\nvofapi64.dll module=%p", static_cast<void *>(module));
    auto getMax = reinterpret_cast<GetMaxVersionFn>(GetProcAddress(module, "NvOFGetMaxSupportedApiVersion"));
    auto createInstance = reinterpret_cast<CreateInstanceFn>(GetProcAddress(module, "NvOFAPICreateInstanceD3D12"));
    if (!getMax || !createInstance) {
        Log("NVOF_EXPORT_RESOLUTION_FAILED getMax=%p createInstance=%p", reinterpret_cast<void *>(getMax), reinterpret_cast<void *>(createInstance));
        return 81;
    }
    uint32_t driverVersion = 0;
    const NV_OF_STATUS versionStatus = getMax(&driverVersion);
    Log("NVOF_API_VERSION_DRIVER=0x%X status=%d", driverVersion, static_cast<int>(versionStatus));
    Log("NVOF_API_VERSION_CLIENT=0x%X", static_cast<unsigned>(NV_OF_API_VERSION));
    if (versionStatus != NV_OF_SUCCESS || driverVersion < NV_OF_API_VERSION) return 82;

    NV_OF_D3D12_API_FUNCTION_LIST api{};
    const NV_OF_STATUS instanceStatus = createInstance(NV_OF_API_VERSION, &api);
    Log("NVOF_FUNCTION_TABLE_RESULT=%d", static_cast<int>(instanceStatus));
    if (instanceStatus != NV_OF_SUCCESS) return 83;

    IDXGIFactory6 *factory = nullptr;
    IDXGIAdapter1 *adapter = nullptr;
    ID3D12Device *device = nullptr;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)))) return 84;
    for (UINT index = 0; ; ++index) {
        IDXGIAdapter1 *candidate = nullptr;
        if (factory->EnumAdapters1(index, &candidate) == DXGI_ERROR_NOT_FOUND) break;
        DXGI_ADAPTER_DESC1 desc{};
        candidate->GetDesc1(&desc);
        if (!(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) && desc.VendorId == 0x10DE) {
            adapter = candidate;
            break;
        }
        Release(candidate);
    }
    if (!adapter || FAILED(D3D12CreateDevice(adapter, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)))) return 85;

    NvOFHandle handle = nullptr;
    const NV_OF_STATUS createStatus = api.nvCreateOpticalFlowD3D12(device, &handle);
    Log("NVOF_INSTANCE_CREATED=%d status=%d handle=%p", createStatus == NV_OF_SUCCESS ? 1 : 0,
        static_cast<int>(createStatus), static_cast<void *>(handle));
    Log("NVOF_GPU_SUPPORTED=%d", createStatus == NV_OF_SUCCESS ? 1 : 0);
    if (createStatus != NV_OF_SUCCESS || !handle) return 86;

    std::vector<uint32_t> grids;
    std::vector<DXGI_FORMAT> inputFormats;
    std::vector<DXGI_FORMAT> outputFormats;
    const bool capsOk = QueryValues(api, handle, NV_OF_CAPS_SUPPORTED_OUTPUT_GRID_SIZES, grids);
    const bool formatsOk = QueryFormats(api, handle, NV_OF_BUFFER_USAGE_INPUT, inputFormats) &&
        QueryFormats(api, handle, NV_OF_BUFFER_USAGE_OUTPUT, outputFormats);
    const bool gridOne = capsOk && std::find(grids.begin(), grids.end(),
        static_cast<uint32_t>(NV_OF_OUTPUT_VECTOR_GRID_SIZE_1)) != grids.end();
    Log("NVOF_GRID_1X1_SUPPORTED=%d", gridOne ? 1 : 0);
    LogFormats("NVOF_INPUT_FORMATS", inputFormats);
    LogFormats("NVOF_OUTPUT_FORMATS", outputFormats);
    const bool bgra = std::find(inputFormats.begin(), inputFormats.end(), DXGI_FORMAT_B8G8R8A8_UNORM) != inputFormats.end();
    Log("NVOF_BGRA8_INPUT_SUPPORTED=%d", bgra ? 1 : 0);

    NV_OF_INIT_PARAMS init{};
    init.width = 256;
    init.height = 256;
    init.outGridSize = NV_OF_OUTPUT_VECTOR_GRID_SIZE_1;
    init.mode = NV_OF_MODE_OPTICALFLOW;
    init.perfLevel = NV_OF_PERF_LEVEL_MEDIUM;
    init.predDirection = NV_OF_PRED_DIRECTION_BOTH;
    init.inputBufferFormat = NV_OF_BUFFER_FORMAT_ABGR8;
    const NV_OF_STATUS initStatus = gridOne && bgra ? api.nvOFInit(handle, &init) : NV_OF_ERR_UNSUPPORTED_FEATURE;
    Log("NVOF_PRED_BOTH_SUPPORTED=%d status=%d", initStatus == NV_OF_SUCCESS ? 1 : 0, static_cast<int>(initStatus));
    const NV_OF_STATUS destroyStatus = api.nvOFDestroy(handle);
    Log("NVOF_DESTROY_RESULT=%d", static_cast<int>(destroyStatus));
    Release(device);
    Release(adapter);
    Release(factory);
    FreeLibrary(module);
    Log("NVOF_PROBE_COMPLETE");
    return formatsOk && gridOne && bgra && initStatus == NV_OF_SUCCESS && destroyStatus == NV_OF_SUCCESS ? 0 : 87;
}

int RunNvofFlowTest() {
    Log("PROCESS_ENTRY");
    Log("ARGS_PARSED");
    constexpr uint32_t width = 256;
    constexpr uint32_t height = 256;
    IDXGIFactory6 *factory = nullptr;
    IDXGIAdapter1 *adapter = nullptr;
    ID3D12Device *device = nullptr;
    ID3D12CommandQueue *queue = nullptr;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)))) return 90;
    for (UINT index = 0; ; ++index) {
        IDXGIAdapter1 *candidate = nullptr;
        if (factory->EnumAdapters1(index, &candidate) == DXGI_ERROR_NOT_FOUND) break;
        DXGI_ADAPTER_DESC1 desc{};
        candidate->GetDesc1(&desc);
        if (!(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) && desc.VendorId == 0x10DE) {
            adapter = candidate;
            break;
        }
        Release(candidate);
    }
    if (!adapter || FAILED(D3D12CreateDevice(adapter, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)))) return 91;
    D3D12_COMMAND_QUEUE_DESC queueDesc{};
    queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    if (FAILED(device->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&queue)))) return 92;
    std::vector<uint8_t> previous(static_cast<size_t>(width) * height * 4);
    std::vector<uint8_t> current(previous.size());
    const auto fill = [&](std::vector<uint8_t> &frame, uint32_t squareX) {
        for (uint32_t y = 0; y < height; ++y) {
            for (uint32_t x = 0; x < width; ++x) {
                const bool square = x >= squareX && x < squareX + 64 && y >= 96 && y < 160;
                uint8_t *pixel = frame.data() + (static_cast<size_t>(y) * width + x) * 4;
                const uint32_t localX = x - squareX;
                pixel[0] = square ? static_cast<uint8_t>(160 + ((localX + y) & 63)) : static_cast<uint8_t>(16 + (x & 31));
                pixel[1] = square ? static_cast<uint8_t>(176 + ((localX * 3 + y) & 63)) : static_cast<uint8_t>(24 + (y & 31));
                pixel[2] = square ? static_cast<uint8_t>(64 + ((localX ^ y) & 63)) : static_cast<uint8_t>(32 + ((x ^ y) & 31));
                pixel[3] = 255;
            }
        }
    };
    fill(previous, 64);
    fill(current, 72);
    NvofD3D12 nvof;
    if (!nvof.Initialize(device, queue, width, height)) return 93;
    std::vector<uint8_t> half;
    std::vector<NvofFlowVector> flow;
    NvofTimings timings{};
    NvofFlowStatistics flowStatistics{};
    if (!nvof.ComputeBackward(previous.data(), current.data(), true, half, &flow, &flowStatistics, &timings)) return 94;
    std::vector<float> objectX;
    std::vector<float> objectY;
    double backgroundMagnitude = 0.0;
    size_t backgroundCount = 0;
    float minimumX = std::numeric_limits<float>::max();
    float maximumX = std::numeric_limits<float>::lowest();
    float minimumY = std::numeric_limits<float>::max();
    float maximumY = std::numeric_limits<float>::lowest();
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            const auto value = flow[static_cast<size_t>(y) * width + x];
            minimumX = std::min(minimumX, value.x);
            maximumX = std::max(maximumX, value.x);
            minimumY = std::min(minimumY, value.y);
            maximumY = std::max(maximumY, value.y);
            if (x >= 80 && x < 128 && y >= 104 && y < 152) {
                objectX.push_back(value.x);
                objectY.push_back(value.y);
            } else if ((x < 48 || x >= 152 || y < 80 || y >= 176)) {
                backgroundMagnitude += std::sqrt(value.x * value.x + value.y * value.y);
                ++backgroundCount;
            }
        }
    }
    const auto mean = [](const std::vector<float> &values) {
        return std::accumulate(values.begin(), values.end(), 0.0) / values.size();
    };
    const auto median = [](std::vector<float> values) {
        const size_t middle = values.size() / 2;
        std::nth_element(values.begin(), values.begin() + middle, values.end());
        return values[middle];
    };
    const double meanX = mean(objectX);
    const double meanY = mean(objectY);
    const double medianX = median(objectX);
    const double medianY = median(objectY);
    const double backgroundMean = backgroundCount ? backgroundMagnitude / backgroundCount : 0.0;
    Log("NVOF_FLOW_DIRECTION=BACKWARD_CURRENT_TO_PREVIOUS");
    Log("NVOF_OBJECT_MEAN_X=%.4f NVOF_OBJECT_MEAN_Y=%.4f", meanX, meanY);
    Log("NVOF_OBJECT_MEDIAN_X=%.4f NVOF_OBJECT_MEDIAN_Y=%.4f", medianX, medianY);
    Log("NVOF_BACKGROUND_MEAN_MAGNITUDE=%.4f", backgroundMean);
    Log("NVOF_FLOW_MIN_X=%.4f MAX_X=%.4f MIN_Y=%.4f MAX_Y=%.4f", minimumX, maximumX, minimumY, maximumY);
    Log("NVOF_FLOW_P95_MAGNITUDE=%.4f NVOF_FLOW_STDDEV_MAGNITUDE=%.4f NVOF_FLOW_NEAR_ZERO_PERCENT=%.3f NVOF_FLOW_UNUSUALLY_LARGE_PERCENT=%.3f",
        flowStatistics.p95Magnitude, flowStatistics.standardDeviationMagnitude,
        flowStatistics.nearZeroPercent, flowStatistics.unusuallyLargePercent);
    Log("NVOF_HALF_BYTE_COUNT=%zu", half.size());
    const bool valid = half.size() == static_cast<size_t>(width) * height * 4 &&
        medianX < -4.0 && medianX > -12.0 && std::abs(medianY) < 2.0 && backgroundMean < 2.0;
    Log("NVOF_FLOW_VALID=%d", valid ? 1 : 0);
    nvof.Shutdown();
    Release(queue);
    Release(device);
    Release(adapter);
    Release(factory);
    Log("NVOF_FLOW_TEST_COMPLETE");
    return valid ? 0 : 95;
}
