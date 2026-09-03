#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl.h>

#include <array>
#include <iostream>
#include <string>
#include <vector>
#include <stdexcept>
#include <chrono>
#include <algorithm>
#include <cmath>
#include <bcrypt.h>

#include "nvOpticalFlowD3D12.h"

using Microsoft::WRL::ComPtr;

namespace {

bool g_enableCost = true;
bool g_r8 = false;
bool g_reverse = false;
bool g_object = false;
uint32_t g_grid = 1;
NV_OF_PERF_LEVEL g_perf = NV_OF_PERF_LEVEL_MEDIUM;
NV_OF_PRED_DIRECTION g_direction = NV_OF_PRED_DIRECTION_FORWARD;
uint32_t g_ringDepth = 0;

const char* statusName(NV_OF_STATUS status)
{
    switch (status) {
    case NV_OF_SUCCESS: return "SUCCESS";
    case NV_OF_ERR_OF_NOT_AVAILABLE: return "OF_NOT_AVAILABLE";
    case NV_OF_ERR_UNSUPPORTED_DEVICE: return "UNSUPPORTED_DEVICE";
    case NV_OF_ERR_INVALID_PARAM: return "INVALID_PARAM";
    case NV_OF_ERR_UNSUPPORTED_FEATURE: return "UNSUPPORTED_FEATURE";
    default: return "OTHER_ERROR";
    }
}

const char* formatName(DXGI_FORMAT format)
{
    switch (format) {
    case DXGI_FORMAT_R8_UNORM: return "R8_UNORM";
    case DXGI_FORMAT_R8G8B8A8_UNORM: return "R8G8B8A8_UNORM";
    case DXGI_FORMAT_B8G8R8A8_UNORM: return "B8G8R8A8_UNORM";
    case DXGI_FORMAT_R16G16_SINT: return "R16G16_SINT";
    case DXGI_FORMAT_R8_UINT: return "R8_UINT";
    default: return "OTHER";
    }
}

void printCaps(NV_OF_D3D12_API_FUNCTION_LIST& api, NvOFHandle handle, NV_OF_CAPS cap, const char* name)
{
    std::array<uint32_t, 16> values{};
    uint32_t size = static_cast<uint32_t>(values.size());
    const auto status = api.nvOFGetCaps(handle, cap, values.data(), &size);
    std::cout << "capability " << name << " status=" << statusName(status) << " values=";
    for (uint32_t i = 0; i < size && i < values.size(); ++i) std::cout << (i ? "," : "") << values[i];
    std::cout << "\n";
}

void printFormats(NV_OF_D3D12_API_FUNCTION_LIST& api, NvOFHandle handle, NV_OF_BUFFER_USAGE usage, const char* name)
{
    uint32_t count = 0;
    auto status = api.nvOFGetSurfaceFormatCountD3D12(handle, usage, NV_OF_MODE_OPTICALFLOW, &count);
    std::cout << "formats " << name << " count_status=" << statusName(status) << " count=" << count << " values=";
    std::vector<DXGI_FORMAT> formats(count);
    if (status == NV_OF_SUCCESS && count) {
        status = api.nvOFGetSurfaceFormatD3D12(handle, usage, NV_OF_MODE_OPTICALFLOW, formats.data());
        for (uint32_t i = 0; i < count; ++i) std::cout << (i ? "," : "") << static_cast<int>(formats[i]) << ":" << formatName(formats[i]);
    }
    std::cout << " list_status=" << statusName(status) << "\n";
}

bool testInit(NV_OF_D3D12_API_FUNCTION_LIST& api, ID3D12Device* device, uint32_t grid, NV_OF_PERF_LEVEL perf, bool cost, NV_OF_PRED_DIRECTION direction)
{
    NvOFHandle handle = nullptr;
    auto status = api.nvCreateOpticalFlowD3D12(device, &handle);
    if (status != NV_OF_SUCCESS) return false;
    NV_OF_INIT_PARAMS params{};
    params.width = 640; params.height = 360;
    params.outGridSize = static_cast<NV_OF_OUTPUT_VECTOR_GRID_SIZE>(grid);
    params.hintGridSize = static_cast<NV_OF_HINT_VECTOR_GRID_SIZE>(grid);
    params.mode = NV_OF_MODE_OPTICALFLOW;
    params.perfLevel = perf;
    params.enableOutputCost = cost ? NV_OF_TRUE : NV_OF_FALSE;
    params.disparityRange = NV_OF_STEREO_DISPARITY_RANGE_UNDEFINED;
    params.predDirection = direction;
    params.inputBufferFormat = NV_OF_BUFFER_FORMAT_ABGR8;
    status = api.nvOFInit(handle, &params);
    api.nvOFDestroy(handle);
    return status == NV_OF_SUCCESS;
}

struct Gpu {
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    uint64_t value = 0;
    ~Gpu() { if (event) CloseHandle(event); }
    void submit()
    {
        if (FAILED(list->Close())) throw std::runtime_error("command list close failed");
        ID3D12CommandList* lists[] = {list.Get()}; queue->ExecuteCommandLists(1, lists);
        ++value; if (FAILED(queue->Signal(fence.Get(), value))) throw std::runtime_error("fence signal failed");
        if (fence->GetCompletedValue() < value) { if (FAILED(fence->SetEventOnCompletion(value, event))) throw std::runtime_error("fence wait setup failed"); WaitForSingleObject(event, INFINITE); }
        if (FAILED(allocator->Reset()) || FAILED(list->Reset(allocator.Get(), nullptr))) throw std::runtime_error("command list reset failed");
    }
};

void waitFence(ID3D12Fence* fence, uint64_t value, HANDLE event, const char* label)
{
    std::cerr << label << " completed=" << fence->GetCompletedValue() << " expected=" << value << "\n";
    if (fence->GetCompletedValue() < value) { if (FAILED(fence->SetEventOnCompletion(value, event))) throw std::runtime_error("fence wait setup failed"); WaitForSingleObject(event, INFINITE); }
    std::cerr << label << " complete\n";
}

void printRegionStats(const std::vector<NV_OF_FLOW_VECTOR>& flow, uint32_t width, uint32_t grid)
{
    std::vector<double> x, y;
    for (uint32_t row = 140 / grid; row < 180 / grid; ++row) for (uint32_t col = 100 / grid; col < 150 / grid; ++col) { const auto& v = flow[row * width + col]; x.push_back(v.flowx / 32.0); y.push_back(v.flowy / 32.0); }
    auto report = [](std::vector<double> values, double truth) { std::sort(values.begin(), values.end()); double mean = 0, mae = 0; for (double value : values) { mean += value; mae += std::abs(value - truth); } mean /= values.size(); double variance = 0; for (double value : values) variance += (value - mean) * (value - mean); auto p = [&](double percentile) { return values[static_cast<size_t>(percentile * (values.size() - 1))]; }; return std::array<double, 8>{p(.1), p(.25), p(.5), p(.75), p(.9), mean, std::sqrt(variance / values.size()), mae / values.size()}; };
    auto xs = report(x, g_reverse ? 8.0 : -8.0), ys = report(y, 0.0); std::cerr << "object_interior count=" << x.size() << " X[p10,p25,p50,p75,p90,mean,sd,mae]=" << xs[0] << "," << xs[1] << "," << xs[2] << "," << xs[3] << "," << xs[4] << "," << xs[5] << "," << xs[6] << "," << xs[7] << " Y[p10,p25,p50,p75,p90,mean,sd,mae]=" << ys[0] << "," << ys[1] << "," << ys[2] << "," << ys[3] << "," << ys[4] << "," << ys[5] << "," << ys[6] << "," << ys[7] << "\n";
}

ComPtr<ID3D12Resource> makeTexture(ID3D12Device* device, uint32_t width, uint32_t height, DXGI_FORMAT format)
{
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{}; desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D; desc.Width = width; desc.Height = height;
    desc.DepthOrArraySize = 1; desc.MipLevels = 1; desc.Format = format; desc.SampleDesc.Count = 1; desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    ComPtr<ID3D12Resource> resource;
    if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&resource)))) throw std::runtime_error("texture allocation failed");
    return resource;
}

void uploadTexture(Gpu& gpu, ID3D12Device* device, ID3D12Resource* destination, const std::vector<uint8_t>& pixels)
{
    auto desc = destination->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{}; UINT rows = 0; UINT64 bytes = 0;
    device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, nullptr, &bytes);
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_UPLOAD; D3D12_RESOURCE_DESC buffer{}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; buffer.Width = bytes; buffer.Height = 1; buffer.DepthOrArraySize = 1; buffer.MipLevels = 1; buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> staging; if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer, D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&staging)))) throw std::runtime_error("upload allocation failed");
    uint8_t* mapped = nullptr; D3D12_RANGE range{0, 0}; staging->Map(0, &range, reinterpret_cast<void**>(&mapped));
    const auto rowBytes = destination->GetDesc().Width * (destination->GetDesc().Format == DXGI_FORMAT_R8_UNORM ? 1 : 4); for (UINT y = 0; y < destination->GetDesc().Height; ++y) memcpy(mapped + footprint.Offset + y * footprint.Footprint.RowPitch, pixels.data() + y * rowBytes, rowBytes); staging->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION src{staging.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; src.PlacedFootprint = footprint; D3D12_TEXTURE_COPY_LOCATION dst{destination, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; dst.SubresourceIndex = 0;
    D3D12_RESOURCE_BARRIER barrier{}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION; barrier.Transition.pResource = destination; barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COMMON; barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_DEST; barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES; gpu.list->ResourceBarrier(1, &barrier); gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST; barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON; gpu.list->ResourceBarrier(1, &barrier); gpu.submit();
}

std::vector<NV_OF_FLOW_VECTOR> readFlow(Gpu& gpu, ID3D12Device* device, ID3D12Resource* source, uint32_t width, uint32_t height, ID3D12Fence* ofaFence, uint64_t ofaValue)
{
    D3D12_RESOURCE_DESC desc = source->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{}; UINT rows = 0; UINT64 bytes = 0; device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, nullptr, &bytes);
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_READBACK; D3D12_RESOURCE_DESC buffer{}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; buffer.Width = bytes; buffer.Height = 1; buffer.DepthOrArraySize = 1; buffer.MipLevels = 1; buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> staging; if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer, D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&staging)))) throw std::runtime_error("readback allocation failed");
    D3D12_TEXTURE_COPY_LOCATION src{source, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; src.SubresourceIndex = 0; D3D12_TEXTURE_COPY_LOCATION dst{staging.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; dst.PlacedFootprint = footprint;
    gpu.queue->Wait(ofaFence, ofaValue); D3D12_RESOURCE_BARRIER barrier{}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION; barrier.Transition.pResource = source; barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COMMON; barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE; barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES; gpu.list->ResourceBarrier(1, &barrier); gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr); barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE; barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON; gpu.list->ResourceBarrier(1, &barrier); gpu.submit();
    std::vector<NV_OF_FLOW_VECTOR> result(width * height); uint8_t* mapped = nullptr; D3D12_RANGE range{0, bytes}; staging->Map(0, &range, reinterpret_cast<void**>(&mapped)); for (uint32_t y = 0; y < height; ++y) memcpy(result.data() + y * width, mapped + footprint.Offset + y * footprint.Footprint.RowPitch, width * sizeof(NV_OF_FLOW_VECTOR)); staging->Unmap(0, nullptr); return result;
}

std::vector<uint8_t> readTextureBytes(Gpu& gpu, ID3D12Device* device, ID3D12Resource* source, uint32_t width, uint32_t height, uint32_t bytesPerPixel)
{
    D3D12_RESOURCE_DESC desc = source->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{}; UINT rows = 0; UINT64 bytes = 0; device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, nullptr, &bytes);
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_READBACK; D3D12_RESOURCE_DESC buffer{}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; buffer.Width = bytes; buffer.Height = 1; buffer.DepthOrArraySize = 1; buffer.MipLevels = 1; buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR; ComPtr<ID3D12Resource> staging; if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer, D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&staging)))) throw std::runtime_error("texture readback allocation failed");
    D3D12_TEXTURE_COPY_LOCATION src{source, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; D3D12_TEXTURE_COPY_LOCATION dst{staging.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; src.SubresourceIndex = 0; dst.PlacedFootprint = footprint; D3D12_RESOURCE_BARRIER barrier{}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION; barrier.Transition.pResource = source; barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COMMON; barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE; barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES; gpu.list->ResourceBarrier(1, &barrier); gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr); barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE; barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON; gpu.list->ResourceBarrier(1, &barrier); gpu.submit();
    std::vector<uint8_t> result(width * height * bytesPerPixel); uint8_t* mapped = nullptr; D3D12_RANGE range{0, bytes}; staging->Map(0, &range, reinterpret_cast<void**>(&mapped)); for (uint32_t y = 0; y < height; ++y) memcpy(result.data() + y * width * bytesPerPixel, mapped + footprint.Offset + y * footprint.Footprint.RowPitch, width * bytesPerPixel); staging->Unmap(0, nullptr); return result;
}

std::string sha256(const std::vector<uint8_t>& bytes)
{
    BCRYPT_ALG_HANDLE algorithm = nullptr; BCRYPT_HASH_HANDLE hash = nullptr; DWORD objectSize = 0, resultSize = 0; BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0); BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&objectSize), sizeof(objectSize), &resultSize, 0); std::vector<uint8_t> object(objectSize), digest(32); BCryptCreateHash(algorithm, &hash, object.data(), objectSize, nullptr, 0, 0); BCryptHashData(hash, const_cast<PUCHAR>(bytes.data()), static_cast<ULONG>(bytes.size()), 0); BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0); BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(algorithm, 0); static const char* digits = "0123456789ABCDEF"; std::string result; for (uint8_t value : digest) { result += digits[value >> 4]; result += digits[value & 15]; } return result;
}

void executeKnownTranslation(NV_OF_D3D12_API_FUNCTION_LIST& api, ID3D12Device* device)
{
    constexpr uint32_t width = 640, height = 360; Gpu gpu;
    D3D12_COMMAND_QUEUE_DESC queueDesc{}; queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT; ComPtr<ID3D12Fence> ofaFence;
    if (FAILED(device->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&gpu.queue))) || FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&gpu.allocator))) || FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, gpu.allocator.Get(), nullptr, IID_PPV_ARGS(&gpu.list))) || FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&gpu.fence))) || FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&ofaFence)))) throw std::runtime_error("GPU queue setup failed");
    gpu.list->Close(); gpu.allocator->Reset(); gpu.list->Reset(gpu.allocator.Get(), nullptr);
    const auto inputFormat = g_r8 ? DXGI_FORMAT_R8_UNORM : DXGI_FORMAT_B8G8R8A8_UNORM; const auto pixelBytes = g_r8 ? 1u : 4u; std::vector<uint8_t> previous(width * height * pixelBytes), current(width * height * pixelBytes); for (uint32_t y = 0; y < height; ++y) for (uint32_t x = 0; x < width; ++x) { const auto value = static_cast<uint8_t>((x * 37u + y * 53u + (x ^ y) * 11u) & 255u); if (g_r8) { previous[y * width + x] = value; current[y * width + x] = x >= 8 ? previous[y * width + x - 8] : 0; } else { for (uint32_t c = 0; c < 4; ++c) { previous[(y * width + x) * 4 + c] = value; current[(y * width + x) * 4 + c] = x >= 8 ? previous[(y * width + x - 8) * 4 + c] : 0; } } }
    if (g_reverse) std::swap(previous, current);
    if (g_object) {
        previous.assign(width * height * 4, 28); current.assign(width * height * 4, 28);
        for (uint32_t y = 120; y < 200; ++y) for (uint32_t x = 80; x < 160; ++x) previous[(y * width + x) * 4 + 2] = 240;
        for (uint32_t y = 120; y < 200; ++y) for (uint32_t x = 88; x < 168; ++x) current[(y * width + x) * 4 + 2] = 240;
    }
    auto input = makeTexture(device, width, height, inputFormat); auto reference = makeTexture(device, width, height, inputFormat); auto output = makeTexture(device, (width + g_grid - 1) / g_grid, (height + g_grid - 1) / g_grid, DXGI_FORMAT_R16G16_SINT); auto cost = makeTexture(device, (width + g_grid - 1) / g_grid, (height + g_grid - 1) / g_grid, DXGI_FORMAT_R8_UINT); auto bwdOutput = makeTexture(device, (width + g_grid - 1) / g_grid, (height + g_grid - 1) / g_grid, DXGI_FORMAT_R16G16_SINT); auto bwdCost = makeTexture(device, (width + g_grid - 1) / g_grid, (height + g_grid - 1) / g_grid, DXGI_FORMAT_R8_UINT);
    auto uploadBegin = std::chrono::steady_clock::now(); uploadTexture(gpu, device, input.Get(), current); uploadTexture(gpu, device, reference.Get(), previous); std::cerr << "upload_ms=" << std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - uploadBegin).count() << "\n"; auto gpuCurrent = readTextureBytes(gpu, device, input.Get(), width, height, pixelBytes); auto gpuPrevious = readTextureBytes(gpu, device, reference.Get(), width, height, pixelBytes); std::cerr << "cpu_current_sha256=" << sha256(current) << " gpu_current_sha256=" << sha256(gpuCurrent) << " cpu_previous_sha256=" << sha256(previous) << " gpu_previous_sha256=" << sha256(gpuPrevious) << " input_integrity=" << ((current == gpuCurrent && previous == gpuPrevious) ? "PASS" : "FAIL") << "\n";
    NvOFHandle handle = nullptr; if (api.nvCreateOpticalFlowD3D12(device, &handle) != NV_OF_SUCCESS) throw std::runtime_error("NVOF instance failed");
    NV_OF_INIT_PARAMS init{}; init.width = width; init.height = height; init.outGridSize = static_cast<NV_OF_OUTPUT_VECTOR_GRID_SIZE>(g_grid); init.hintGridSize = static_cast<NV_OF_HINT_VECTOR_GRID_SIZE>(g_grid); init.mode = NV_OF_MODE_OPTICALFLOW; init.perfLevel = g_perf; init.enableOutputCost = g_enableCost ? NV_OF_TRUE : NV_OF_FALSE; init.disparityRange = NV_OF_STEREO_DISPARITY_RANGE_UNDEFINED; init.predDirection = g_direction; init.inputBufferFormat = g_r8 ? NV_OF_BUFFER_FORMAT_GRAYSCALE8 : NV_OF_BUFFER_FORMAT_ABGR8;
    if (api.nvOFInit(handle, &init) != NV_OF_SUCCESS) throw std::runtime_error("NVOF init failed"); std::cerr << "initialized\n";
    auto registerResource = [&](ID3D12Resource* resource, NvOFGPUBufferHandle* result, NV_OF_BUFFER_USAGE usage, DXGI_FORMAT format) { NV_OF_REGISTER_RESOURCE_PARAMS_D3D12 params{}; params.resource = resource; params.inputFencePoint = {gpu.fence.Get(), gpu.value}; params.hOFGpuBuffer = result; params.outputFencePoint = {ofaFence.Get(), 0}; if (api.nvOFRegisterResourceD3D12(handle, &params) != NV_OF_SUCCESS) throw std::runtime_error("resource registration failed"); (void)usage; (void)format; };
    NvOFGPUBufferHandle inputHandle = nullptr, referenceHandle = nullptr, outputHandle = nullptr, costHandle = nullptr, bwdOutputHandle = nullptr, bwdCostHandle = nullptr;
    registerResource(input.Get(), &inputHandle, NV_OF_BUFFER_USAGE_INPUT, inputFormat); std::cerr << "registered input\n"; registerResource(reference.Get(), &referenceHandle, NV_OF_BUFFER_USAGE_INPUT, inputFormat); std::cerr << "registered reference\n"; registerResource(output.Get(), &outputHandle, NV_OF_BUFFER_USAGE_OUTPUT, DXGI_FORMAT_R16G16_SINT); std::cerr << "registered output\n"; if (g_enableCost) { registerResource(cost.Get(), &costHandle, NV_OF_BUFFER_USAGE_COST, DXGI_FORMAT_R8_UINT); std::cerr << "registered cost\n"; } if (g_direction == NV_OF_PRED_DIRECTION_BOTH) { registerResource(bwdOutput.Get(), &bwdOutputHandle, NV_OF_BUFFER_USAGE_OUTPUT, DXGI_FORMAT_R16G16_SINT); std::cerr << "registered backward output\n"; if (g_enableCost) { registerResource(bwdCost.Get(), &bwdCostHandle, NV_OF_BUFFER_USAGE_COST, DXGI_FORMAT_R8_UINT); std::cerr << "registered backward cost\n"; } }
    NV_OF_FENCE_POINT inputFence{gpu.fence.Get(), gpu.value}; NV_OF_FENCE_POINT outputFence{ofaFence.Get(), 1}; NV_OF_EXECUTE_INPUT_PARAMS_D3D12 executeIn{}; executeIn.inputFrame = inputHandle; executeIn.referenceFrame = referenceHandle; executeIn.disableTemporalHints = NV_OF_TRUE; executeIn.numFencePoints = 1; executeIn.fencePoint = &inputFence; NV_OF_EXECUTE_OUTPUT_PARAMS_D3D12 executeOut{}; executeOut.outputBuffer = outputHandle; executeOut.outputCostBuffer = g_enableCost ? costHandle : nullptr; executeOut.bwdOutputBuffer = g_direction == NV_OF_PRED_DIRECTION_BOTH ? bwdOutputHandle : nullptr; executeOut.bwdOutputCostBuffer = g_direction == NV_OF_PRED_DIRECTION_BOTH && g_enableCost ? bwdCostHandle : nullptr; executeOut.fencePoint = &outputFence;
    std::cerr << "executing\n"; auto submitBegin = std::chrono::steady_clock::now(); if (api.nvOFExecuteD3D12(handle, &executeIn, &executeOut) != NV_OF_SUCCESS) throw std::runtime_error("NVOF execute failed"); std::cerr << "execute_cpu_us=" << std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - submitBegin).count() << "\n"; waitFence(ofaFence.Get(), outputFence.value, gpu.event, "NVOFA");
    const auto outputWidth = (width + g_grid - 1) / g_grid, outputHeight = (height + g_grid - 1) / g_grid; auto readbackBegin = std::chrono::steady_clock::now(); auto forward = readFlow(gpu, device, output.Get(), outputWidth, outputHeight, ofaFence.Get(), outputFence.value); std::cerr << "readback_total_ms=" << std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - readbackBegin).count() << "\n"; waitFence(gpu.fence.Get(), gpu.value, gpu.event, "D3D12"); auto print = [](const char* name, const NV_OF_FLOW_VECTOR& value) { std::cerr << name << " raw=" << value.flowx << "," << value.flowy << " pixels=" << value.flowx / 32.0 << "," << value.flowy / 32.0 << "\n"; };
    print("input_current_reference_previous", forward[(height / 2 / g_grid) * outputWidth + 120 / g_grid]); printRegionStats(forward, outputWidth, g_grid);
    if (g_enableCost) { auto costBytes = readTextureBytes(gpu, device, cost.Get(), outputWidth, outputHeight, 1); double costMean = 0, errorMean = 0, costSq = 0, errorSq = 0, cross = 0; size_t count = 0; for (uint32_t row = 140 / g_grid; row < 180 / g_grid; ++row) for (uint32_t col = 100 / g_grid; col < 150 / g_grid; ++col) { const auto& v = forward[row * outputWidth + col]; double error = std::hypot(v.flowx / 32.0 - (g_reverse ? 8.0 : -8.0), v.flowy / 32.0); double c = costBytes[row * outputWidth + col]; costMean += c; errorMean += error; costSq += c * c; errorSq += error * error; cross += c * error; ++count; } costMean /= count; errorMean /= count; double correlation = (cross / count - costMean * errorMean) / std::sqrt((costSq / count - costMean * costMean) * (errorSq / count - errorMean * errorMean)); std::cerr << "cost_object_interior_mean=" << costMean << " error_mean=" << errorMean << " pearson_cost_error=" << correlation << "\n"; }
    auto begin = std::chrono::steady_clock::now(); for (int i = 0; i < 120; ++i) { ++outputFence.value; if (api.nvOFExecuteD3D12(handle, &executeIn, &executeOut) != NV_OF_SUCCESS) throw std::runtime_error("NVOF repeated execute failed"); } waitFence(ofaFence.Get(), outputFence.value, gpu.event, "NVOFA repeated"); auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - begin).count(); std::cerr << "flow_ms_per_frame=" << elapsed / 120.0 << "\n";
    auto unregisterResource = [&](NvOFGPUBufferHandle resource) { NV_OF_UNREGISTER_RESOURCE_PARAMS_D3D12 params{}; params.hOFGpuBuffer = resource; api.nvOFUnregisterResourceD3D12(&params); };
    std::cerr << "CLEANUP 03 unregister input\n"; unregisterResource(inputHandle); std::cerr << "CLEANUP 04 unregister reference\n"; unregisterResource(referenceHandle); std::cerr << "CLEANUP 05 unregister output\n"; unregisterResource(outputHandle); if (g_enableCost) { std::cerr << "CLEANUP 06 unregister cost\n"; unregisterResource(costHandle); }
    // OFA and application/readback fences are distinct; complete both before unregistering, then release resources before NvOFDestroy.
    if (g_direction == NV_OF_PRED_DIRECTION_BOTH) { std::cerr << "CLEANUP 06b unregister backward output\n"; unregisterResource(bwdOutputHandle); if (g_enableCost) { std::cerr << "CLEANUP 06c unregister backward cost\n"; unregisterResource(bwdCostHandle); } } input.Reset(); reference.Reset(); output.Reset(); cost.Reset(); bwdOutput.Reset(); bwdCost.Reset(); std::cerr << "CLEANUP 07 resources released\n";
    std::cerr << "CLEANUP 12 nvOFDestroy begin\n"; api.nvOFDestroy(handle); std::cerr << "CLEANUP 13 nvOFDestroy returned\n";
}

void executeRingThroughput(NV_OF_D3D12_API_FUNCTION_LIST& api, ID3D12Device* device)
{
    constexpr uint32_t width = 640, height = 360, warmup = 30, measured = 240;
    if (g_ringDepth != 1 && g_ringDepth != 2 && g_ringDepth != 4)
        throw std::runtime_error("NVOF_RING must be 1, 2, or 4");

    Gpu gpu;
    ComPtr<ID3D12Fence> ofaFence;
    D3D12_COMMAND_QUEUE_DESC queueDesc{};
    queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    if (FAILED(device->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&gpu.queue))) ||
        FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&gpu.allocator))) ||
        FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, gpu.allocator.Get(), nullptr, IID_PPV_ARGS(&gpu.list))) ||
        FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&gpu.fence))) ||
        FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&ofaFence))))
        throw std::runtime_error("ring queue setup failed");
    gpu.list->Close();
    gpu.allocator->Reset();
    gpu.list->Reset(gpu.allocator.Get(), nullptr);

    const auto inputFormat = g_r8 ? DXGI_FORMAT_R8_UNORM : DXGI_FORMAT_B8G8R8A8_UNORM;
    const auto pixelBytes = g_r8 ? 1u : 4u;
    std::vector<uint8_t> previous(width * height * pixelBytes), current(width * height * pixelBytes);
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            const auto value = static_cast<uint8_t>((x * 37u + y * 53u + (x ^ y) * 11u) & 255u);
            const auto source = x >= 8 ? (x - 8) : 0;
            if (g_r8) {
                previous[y * width + x] = value;
                current[y * width + x] = x >= 8 ? previous[y * width + source] : 0;
            } else {
                for (uint32_t c = 0; c < 4; ++c) {
                    previous[(y * width + x) * 4 + c] = value;
                    current[(y * width + x) * 4 + c] = x >= 8 ? previous[(y * width + source) * 4 + c] : 0;
                }
            }
        }
    }
    if (g_reverse) std::swap(previous, current);

    struct Slot {
        ComPtr<ID3D12Resource> input, reference, output, cost, bwdOutput, bwdCost;
        NvOFGPUBufferHandle inputHandle = nullptr, referenceHandle = nullptr;
        NvOFGPUBufferHandle outputHandle = nullptr, costHandle = nullptr;
        NvOFGPUBufferHandle bwdOutputHandle = nullptr, bwdCostHandle = nullptr;
        NV_OF_FENCE_POINT outputFence{};
        uint64_t lastOFA = 0;
    };
    std::vector<Slot> slots(g_ringDepth);
    const auto outputWidth = (width + g_grid - 1) / g_grid;
    const auto outputHeight = (height + g_grid - 1) / g_grid;
    for (auto& slot : slots) {
        slot.input = makeTexture(device, width, height, inputFormat);
        slot.reference = makeTexture(device, width, height, inputFormat);
        slot.output = makeTexture(device, outputWidth, outputHeight, DXGI_FORMAT_R16G16_SINT);
        if (g_enableCost) slot.cost = makeTexture(device, outputWidth, outputHeight, DXGI_FORMAT_R8_UINT);
        if (g_direction == NV_OF_PRED_DIRECTION_BOTH) {
            slot.bwdOutput = makeTexture(device, outputWidth, outputHeight, DXGI_FORMAT_R16G16_SINT);
            if (g_enableCost) slot.bwdCost = makeTexture(device, outputWidth, outputHeight, DXGI_FORMAT_R8_UINT);
        }
        uploadTexture(gpu, device, slot.input.Get(), current);
        uploadTexture(gpu, device, slot.reference.Get(), previous);
    }

    NvOFHandle handle = nullptr;
    if (api.nvCreateOpticalFlowD3D12(device, &handle) != NV_OF_SUCCESS)
        throw std::runtime_error("NVOF ring instance failed");
    NV_OF_INIT_PARAMS init{};
    init.width = width; init.height = height;
    init.outGridSize = static_cast<NV_OF_OUTPUT_VECTOR_GRID_SIZE>(g_grid);
    init.hintGridSize = static_cast<NV_OF_HINT_VECTOR_GRID_SIZE>(g_grid);
    init.mode = NV_OF_MODE_OPTICALFLOW; init.perfLevel = g_perf;
    init.enableOutputCost = g_enableCost ? NV_OF_TRUE : NV_OF_FALSE;
    init.disparityRange = NV_OF_STEREO_DISPARITY_RANGE_UNDEFINED;
    init.predDirection = g_direction;
    init.inputBufferFormat = g_r8 ? NV_OF_BUFFER_FORMAT_GRAYSCALE8 : NV_OF_BUFFER_FORMAT_ABGR8;
    if (api.nvOFInit(handle, &init) != NV_OF_SUCCESS) throw std::runtime_error("NVOF ring init failed");

    auto registerResource = [&](ID3D12Resource* resource, NvOFGPUBufferHandle* result) {
        NV_OF_REGISTER_RESOURCE_PARAMS_D3D12 params{};
        params.resource = resource;
        params.inputFencePoint = {gpu.fence.Get(), gpu.value};
        params.hOFGpuBuffer = result;
        params.outputFencePoint = {ofaFence.Get(), 0};
        if (api.nvOFRegisterResourceD3D12(handle, &params) != NV_OF_SUCCESS)
            throw std::runtime_error("ring resource registration failed");
    };
    for (auto& slot : slots) {
        registerResource(slot.input.Get(), &slot.inputHandle);
        registerResource(slot.reference.Get(), &slot.referenceHandle);
        registerResource(slot.output.Get(), &slot.outputHandle);
        if (g_enableCost) registerResource(slot.cost.Get(), &slot.costHandle);
        if (g_direction == NV_OF_PRED_DIRECTION_BOTH) {
            registerResource(slot.bwdOutput.Get(), &slot.bwdOutputHandle);
            if (g_enableCost) registerResource(slot.bwdCost.Get(), &slot.bwdCostHandle);
        }
    }

    NV_OF_FENCE_POINT inputFence{gpu.fence.Get(), gpu.value};
    uint64_t ofaValue = 0;
    auto execute = [&](Slot& slot, double* submissionCpuUs) {
        if (slot.lastOFA) waitFence(ofaFence.Get(), slot.lastOFA, gpu.event, "NVOFA slot reuse");
        NV_OF_EXECUTE_INPUT_PARAMS_D3D12 executeIn{};
        executeIn.inputFrame = slot.inputHandle; executeIn.referenceFrame = slot.referenceHandle;
        executeIn.disableTemporalHints = NV_OF_TRUE; executeIn.numFencePoints = 1;
        executeIn.fencePoint = &inputFence;
        NV_OF_EXECUTE_OUTPUT_PARAMS_D3D12 executeOut{};
        executeOut.outputBuffer = slot.outputHandle;
        executeOut.outputCostBuffer = g_enableCost ? slot.costHandle : nullptr;
        executeOut.bwdOutputBuffer = g_direction == NV_OF_PRED_DIRECTION_BOTH ? slot.bwdOutputHandle : nullptr;
        executeOut.bwdOutputCostBuffer = g_direction == NV_OF_PRED_DIRECTION_BOTH && g_enableCost ? slot.bwdCostHandle : nullptr;
        slot.outputFence = {ofaFence.Get(), ++ofaValue};
        executeOut.fencePoint = &slot.outputFence;
        const auto begin = std::chrono::steady_clock::now();
        if (api.nvOFExecuteD3D12(handle, &executeIn, &executeOut) != NV_OF_SUCCESS)
            throw std::runtime_error("NVOF ring execute failed");
        if (submissionCpuUs) *submissionCpuUs += std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - begin).count();
        slot.lastOFA = slot.outputFence.value;
    };
    for (uint32_t i = 0; i < warmup; ++i) execute(slots[i % g_ringDepth], nullptr);
    double submissionCpuUs = 0;
    const auto measuredBegin = std::chrono::steady_clock::now();
    for (uint32_t i = 0; i < measured; ++i) execute(slots[(warmup + i) % g_ringDepth], &submissionCpuUs);
    waitFence(ofaFence.Get(), ofaValue, gpu.event, "NVOFA ring final");
    const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - measuredBegin).count();
    std::cout << "ring_depth=" << g_ringDepth << " grid=" << g_grid << " warmup=" << warmup << " measured=" << measured
              << " submission_cpu_us_total=" << submissionCpuUs
              << " submission_cpu_us_per_execute=" << submissionCpuUs / measured
              << " throughput_fps=" << measured / elapsed << "\n";

    auto unregisterResource = [&](NvOFGPUBufferHandle resource) {
        NV_OF_UNREGISTER_RESOURCE_PARAMS_D3D12 params{}; params.hOFGpuBuffer = resource;
        api.nvOFUnregisterResourceD3D12(&params);
    };
    for (auto& slot : slots) {
        unregisterResource(slot.inputHandle); unregisterResource(slot.referenceHandle); unregisterResource(slot.outputHandle);
        if (g_enableCost) unregisterResource(slot.costHandle);
        if (g_direction == NV_OF_PRED_DIRECTION_BOTH) {
            unregisterResource(slot.bwdOutputHandle); if (g_enableCost) unregisterResource(slot.bwdCostHandle);
        }
        slot.input.Reset(); slot.reference.Reset(); slot.output.Reset(); slot.cost.Reset();
        slot.bwdOutput.Reset(); slot.bwdCost.Reset();
    }
    api.nvOFDestroy(handle);
}

} // namespace

int wmain()
{
    char option[32]{}; if (GetEnvironmentVariableA("NVOF_NO_COST", option, sizeof(option))) g_enableCost = false; if (GetEnvironmentVariableA("NVOF_R8", option, sizeof(option))) g_r8 = true; if (GetEnvironmentVariableA("NVOF_REVERSE", option, sizeof(option))) g_reverse = true; if (GetEnvironmentVariableA("NVOF_OBJECT", option, sizeof(option))) { g_object = true; g_r8 = false; } if (GetEnvironmentVariableA("NVOF_FAST", option, sizeof(option))) g_perf = NV_OF_PERF_LEVEL_FAST; if (GetEnvironmentVariableA("NVOF_SLOW", option, sizeof(option))) g_perf = NV_OF_PERF_LEVEL_SLOW; if (GetEnvironmentVariableA("NVOF_BOTH", option, sizeof(option))) g_direction = NV_OF_PRED_DIRECTION_BOTH; if (GetEnvironmentVariableA("NVOF_GRID", option, sizeof(option))) g_grid = static_cast<uint32_t>(std::stoul(option)); if (GetEnvironmentVariableA("NVOF_RING", option, sizeof(option))) g_ringDepth = static_cast<uint32_t>(std::stoul(option));
    ComPtr<IDXGIFactory6> factory;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)))) return 2;
    ComPtr<ID3D12Device> device;
    std::wstring adapterName;
    for (UINT index = 0; ; ++index) {
        ComPtr<IDXGIAdapter1> adapter;
        if (factory->EnumAdapterByGpuPreference(index, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&adapter)) == DXGI_ERROR_NOT_FOUND) break;
        DXGI_ADAPTER_DESC1 desc{}; adapter->GetDesc1(&desc);
        if ((desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) || desc.VendorId != 0x10DE) continue;
        if (SUCCEEDED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device)))) {
            adapterName = desc.Description; break;
        }
    }
    if (!device) { std::cerr << "no NVIDIA D3D12 adapter\n"; return 3; }
    HMODULE module = LoadLibraryExW(L"C:\\Windows\\System32\\nvofapi64.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module) { std::cerr << "nvofapi64.dll load failed: " << GetLastError() << "\n"; return 4; }
    using CreateFn = NV_OF_STATUS (NVOFAPI*)(uint32_t, NV_OF_D3D12_API_FUNCTION_LIST*);
    auto create = reinterpret_cast<CreateFn>(GetProcAddress(module, "NvOFAPICreateInstanceD3D12"));
    if (!create) { std::cerr << "D3D12 entry point missing\n"; FreeLibrary(module); return 5; }
    NV_OF_D3D12_API_FUNCTION_LIST api{};
    auto status = create(NV_OF_API_VERSION, &api);
    std::wcout << L"adapter=" << adapterName << L"\n";
    std::cout << "api_requested=" << NV_OF_API_VERSION << " create_status=" << statusName(status) << "\n";
    if (status != NV_OF_SUCCESS) { FreeLibrary(module); return 6; }
    NvOFHandle handle = nullptr;
    status = api.nvCreateOpticalFlowD3D12(device.Get(), &handle);
    std::cout << "instance_status=" << statusName(status) << "\n";
    if (status != NV_OF_SUCCESS) { FreeLibrary(module); return 7; }
    printCaps(api, handle, NV_OF_CAPS_SUPPORTED_OUTPUT_GRID_SIZES, "output_grids");
    printCaps(api, handle, NV_OF_CAPS_SUPPORTED_HINT_GRID_SIZES, "hint_grids");
    printCaps(api, handle, NV_OF_CAPS_WIDTH_MIN, "width_min");
    printCaps(api, handle, NV_OF_CAPS_HEIGHT_MIN, "height_min");
    printCaps(api, handle, NV_OF_CAPS_WIDTH_MAX, "width_max");
    printCaps(api, handle, NV_OF_CAPS_HEIGHT_MAX, "height_max");
    printCaps(api, handle, NV_OF_CAPS_SUPPORT_ROI, "roi");
    printFormats(api, handle, NV_OF_BUFFER_USAGE_INPUT, "input");
    printFormats(api, handle, NV_OF_BUFFER_USAGE_OUTPUT, "output");
    printFormats(api, handle, NV_OF_BUFFER_USAGE_COST, "cost");
    api.nvOFDestroy(handle);
    for (uint32_t grid : {1u, 2u, 4u}) for (auto perf : {NV_OF_PERF_LEVEL_FAST, NV_OF_PERF_LEVEL_MEDIUM, NV_OF_PERF_LEVEL_SLOW})
        std::cout << "init grid=" << grid << " perf=" << perf << " cost=1 forward=" << testInit(api, device.Get(), grid, perf, true, NV_OF_PRED_DIRECTION_FORWARD) << " both=" << testInit(api, device.Get(), grid, perf, true, NV_OF_PRED_DIRECTION_BOTH) << "\n";
    if (g_ringDepth) executeRingThroughput(api, device.Get()); else executeKnownTranslation(api, device.Get());
    FreeLibrary(module);
    return 0;
}
