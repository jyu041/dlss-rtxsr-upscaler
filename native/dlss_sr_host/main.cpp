#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wincodec.h>
#include <wrl/client.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <io.h>
#include <fcntl.h>
#include <string>
#include <vector>

#include "nvsdk_ngx.h"
#include "nvsdk_ngx_helpers.h"

using Microsoft::WRL::ComPtr;
namespace fs = std::filesystem;

namespace {
constexpr char kProjectId[] = "9f4c4f6d-2f4e-4e88-9e4d-4e8f4d2b7b1a";
constexpr char kEngineVersion[] = "standalone-d3d12-1";

std::wstring resultName(NVSDK_NGX_Result result)
{
    const wchar_t* text = GetNGXResultAsString(result);
    return text ? text : L"unknown";
}

bool succeeded(NVSDK_NGX_Result result)
{
    return NVSDK_NGX_SUCCEED(result);
}

struct Context {
    ComPtr<IDXGIAdapter1> adapter;
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    HANDLE fenceEvent = nullptr;
    UINT64 fenceValue = 0;

    ~Context()
    {
        if (fenceEvent) CloseHandle(fenceEvent);
    }

    bool initialize()
    {
        ComPtr<IDXGIFactory6> factory;
        HRESULT hr = CreateDXGIFactory2(0, IID_PPV_ARGS(&factory));
        if (FAILED(hr)) return false;

        for (UINT index = 0; ; ++index) {
            ComPtr<IDXGIAdapter1> candidate;
            if (factory->EnumAdapterByGpuPreference(index, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                     IID_PPV_ARGS(&candidate)) == DXGI_ERROR_NOT_FOUND)
                break;
            DXGI_ADAPTER_DESC1 desc{};
            candidate->GetDesc1(&desc);
            if (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE || desc.VendorId != 0x10DE) continue;
            if (FAILED(D3D12CreateDevice(candidate.Get(), D3D_FEATURE_LEVEL_12_0,
                                         IID_PPV_ARGS(&device)))) continue;
            adapter = candidate;
            std::wcerr << L"adapter=" << desc.Description << L" vendor=0x" << std::hex
                       << desc.VendorId << L" device=0x" << desc.DeviceId << std::dec
                       << L" vram=" << (desc.DedicatedVideoMemory / (1024ull * 1024ull))
                       << L"MiB feature_level=12_0\n";
            break;
        }
        if (!device) return false;

        D3D12_COMMAND_QUEUE_DESC queueDesc{};
        queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (FAILED(device->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&queue))) ||
            FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator))) ||
            FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                              IID_PPV_ARGS(&list))) ||
            FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)))) return false;
        fenceEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        return fenceEvent != nullptr;
    }

    bool wait()
    {
        ++fenceValue;
        if (FAILED(queue->Signal(fence.Get(), fenceValue))) return false;
        if (fence->GetCompletedValue() < fenceValue) {
            if (FAILED(fence->SetEventOnCompletion(fenceValue, fenceEvent))) return false;
            return WaitForSingleObject(fenceEvent, INFINITE) == WAIT_OBJECT_0;
        }
        return true;
    }

    bool submit()
    {
        if (FAILED(list->Close())) return false;
        ID3D12CommandList* lists[] = {list.Get()};
        queue->ExecuteCommandLists(1, lists);
        return wait();
    }
};

struct Texture {
    ComPtr<ID3D12Resource> resource;
    UINT width = 0;
    UINT height = 0;
};

bool createTexture(Context& context, UINT width, UINT height, DXGI_FORMAT format,
                   D3D12_RESOURCE_FLAGS flags, D3D12_RESOURCE_STATES state, Texture& out)
{
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
    desc.Flags = flags;
    if (FAILED(context.device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state,
                                                       nullptr, IID_PPV_ARGS(&out.resource)))) return false;
    out.width = width;
    out.height = height;
    return true;
}

bool uploadTexture(Context& context, const Texture& texture, const std::vector<unsigned char>& bytes,
                   std::vector<ComPtr<ID3D12Resource>>& uploads)
{
    D3D12_RESOURCE_DESC desc = texture.resource->GetDesc();
    UINT64 uploadSize = 0;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows = 0;
    UINT64 rowSize = 0;
    context.device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, &rowSize, &uploadSize);
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_UPLOAD;
    D3D12_RESOURCE_DESC buffer{};
    buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    buffer.Width = uploadSize;
    buffer.Height = 1;
    buffer.DepthOrArraySize = 1;
    buffer.MipLevels = 1;
    buffer.SampleDesc.Count = 1;
    buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> upload;
    if (FAILED(context.device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
                                                        D3D12_RESOURCE_STATE_GENERIC_READ, nullptr,
                                                        IID_PPV_ARGS(&upload)))) return false;
    unsigned char* mapped = nullptr;
    if (FAILED(upload->Map(0, nullptr, reinterpret_cast<void**>(&mapped)))) return false;
    const size_t sourceRowBytes = bytes.size() / texture.height;
    for (UINT row = 0; row < rows; ++row)
        memcpy(mapped + footprint.Offset + row * footprint.Footprint.RowPitch,
               bytes.data() + row * sourceRowBytes, static_cast<size_t>(rowSize));
    upload->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION source{};
    source.pResource = upload.Get();
    source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    source.PlacedFootprint = footprint;
    D3D12_TEXTURE_COPY_LOCATION destination{};
    destination.pResource = texture.resource.Get();
    destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    context.list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
    uploads.push_back(upload);
    return true;
}

uint16_t floatToHalf(float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    const uint32_t sign = (bits >> 16) & 0x8000;
    int exponent = static_cast<int>((bits >> 23) & 0xff) - 127 + 15;
    uint32_t mantissa = bits & 0x7fffff;
    if (exponent <= 0) return static_cast<uint16_t>(sign);
    if (exponent >= 31) return static_cast<uint16_t>(sign | 0x7c00);
    return static_cast<uint16_t>(sign | (static_cast<uint32_t>(exponent) << 10) | (mantissa >> 13));
}

float halfToFloat(uint16_t value)
{
    const uint32_t sign = (value & 0x8000) << 16;
    uint32_t exponent = (value >> 10) & 0x1f;
    uint32_t mantissa = value & 0x3ff;
    if (exponent == 0) return 0.0f;
    if (exponent == 31) exponent = 255;
    else exponent += 127 - 15;
    uint32_t bits = sign | (exponent << 23) | (mantissa << 13);
    float result;
    memcpy(&result, &bits, sizeof(result));
    return result;
}

bool writePng(const fs::path& path, UINT width, UINT height, const std::vector<unsigned char>& rgba)
{
    ComPtr<IWICImagingFactory> factory;
    if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&factory)))) return false;
    ComPtr<IWICStream> stream;
    ComPtr<IWICBitmapEncoder> encoder;
    ComPtr<IWICBitmapFrameEncode> frame;
    if (FAILED(factory->CreateStream(&stream)) || FAILED(stream->InitializeFromFilename(path.c_str(), GENERIC_WRITE)) ||
        FAILED(factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, &encoder)) ||
        FAILED(encoder->Initialize(stream.Get(), WICBitmapEncoderNoCache)) ||
        FAILED(encoder->CreateNewFrame(&frame, nullptr)) || FAILED(frame->Initialize(nullptr)) ||
        FAILED(frame->SetSize(width, height))) return false;
    WICPixelFormatGUID format = GUID_WICPixelFormat32bppRGBA;
    if (FAILED(frame->SetPixelFormat(&format)) || FAILED(frame->WritePixels(height, width * 4,
                                                                            static_cast<UINT>(rgba.size()),
                                                                            const_cast<BYTE*>(rgba.data()))) ||
        FAILED(frame->Commit()) || FAILED(encoder->Commit())) return false;
    return true;
}

std::vector<unsigned char> syntheticColor(UINT width, UINT height)
{
    std::vector<unsigned char> pixels(static_cast<size_t>(width) * height * 8);
    auto* out = reinterpret_cast<uint16_t*>(pixels.data());
    for (UINT y = 0; y < height; ++y) for (UINT x = 0; x < width; ++x) {
        const float diagonal = ((x + y * 3) % 47 < 2) ? 1.0f : 0.0f;
        const float checker = ((x / 16 + y / 16) & 1) ? 0.15f : 0.8f;
        const size_t i = (static_cast<size_t>(y) * width + x) * 4;
        out[i + 0] = floatToHalf(std::clamp(x / float(width - 1) + diagonal, 0.0f, 1.0f));
        out[i + 1] = floatToHalf(std::clamp(y / float(height - 1), 0.0f, 1.0f));
        out[i + 2] = floatToHalf(checker);
        out[i + 3] = floatToHalf(1.0f);
    }
    return pixels;
}

std::vector<unsigned char> rgbaFromHalf(const std::vector<unsigned char>& bytes)
{
    const auto* input = reinterpret_cast<const uint16_t*>(bytes.data());
    std::vector<unsigned char> rgba(bytes.size() / 2);
    for (size_t i = 0; i < rgba.size() / 4; ++i) {
        rgba[i * 4 + 0] = static_cast<unsigned char>(std::clamp(halfToFloat(input[i * 4 + 0]), 0.0f, 1.0f) * 255.0f);
        rgba[i * 4 + 1] = static_cast<unsigned char>(std::clamp(halfToFloat(input[i * 4 + 1]), 0.0f, 1.0f) * 255.0f);
        rgba[i * 4 + 2] = static_cast<unsigned char>(std::clamp(halfToFloat(input[i * 4 + 2]), 0.0f, 1.0f) * 255.0f);
        rgba[i * 4 + 3] = 255;
    }
    return rgba;
}

bool readbackTexture(Context& context, const Texture& texture, std::vector<unsigned char>& bytes)
{
    const D3D12_RESOURCE_DESC desc = texture.resource->GetDesc();
    UINT64 readbackSize = 0;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows = 0;
    UINT64 rowSize = 0;
    context.device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, &rowSize, &readbackSize);
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC buffer{};
    buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    buffer.Width = readbackSize;
    buffer.Height = 1;
    buffer.DepthOrArraySize = 1;
    buffer.MipLevels = 1;
    buffer.SampleDesc.Count = 1;
    buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> readback;
    if (FAILED(context.device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
                                                        D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                                        IID_PPV_ARGS(&readback)))) return false;
    D3D12_TEXTURE_COPY_LOCATION source{};
    source.pResource = texture.resource.Get();
    source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    D3D12_TEXTURE_COPY_LOCATION destination{};
    destination.pResource = readback.Get();
    destination.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    destination.PlacedFootprint = footprint;
    context.list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
    if (!context.submit()) return false;
    unsigned char* mapped = nullptr;
    if (FAILED(readback->Map(0, nullptr, reinterpret_cast<void**>(&mapped)))) return false;
    bytes.resize(static_cast<size_t>(rowSize) * texture.height);
    for (UINT row = 0; row < rows; ++row)
        memcpy(bytes.data() + row * rowSize, mapped + footprint.Offset + row * footprint.Footprint.RowPitch,
               static_cast<size_t>(rowSize));
    readback->Unmap(0, nullptr);
    return true;
}

#pragma pack(push, 1)
struct StreamInputHeader {
    uint32_t magic;
    uint32_t frame;
    uint32_t width;
    uint32_t height;
    uint32_t reset;
    uint32_t colorBytes;
    uint32_t motionBytes;
};

struct StreamOutputHeader {
    uint32_t magic;
    uint32_t frame;
    uint32_t width;
    uint32_t height;
    uint32_t status;
    uint32_t colorBytes;
};
#pragma pack(pop)

constexpr uint32_t kStreamInputMagic = 0x31524644;  // DFR1
constexpr uint32_t kStreamOutputMagic = 0x31524644; // DFR1

bool readExact(void* destination, size_t size)
{
    return std::cin.read(static_cast<char*>(destination), static_cast<std::streamsize>(size)).good();
}

bool writeExact(const void* source, size_t size)
{
    std::cout.write(static_cast<const char*>(source), static_cast<std::streamsize>(size));
    return std::cout.good();
}

int runStream(const fs::path& root, UINT inputWidth, UINT inputHeight, UINT outputWidth, UINT outputHeight,
              NVSDK_NGX_PerfQuality_Value perf, int preset)
{
    if (!inputWidth || !inputHeight || !outputWidth || !outputHeight ||
        inputWidth > 7680 || inputHeight > 4320 || outputWidth > 7680 || outputHeight > 4320) return 2;
    Context context;
    if (!context.initialize()) { std::wcerr << L"stream D3D12 initialization failed\n"; return 1; }
    fs::path appData = root / "ngx-data";
    fs::create_directories(appData);
    NVSDK_NGX_Result init = NVSDK_NGX_D3D12_Init_with_ProjectID(
        kProjectId, NVSDK_NGX_ENGINE_TYPE_CUSTOM, kEngineVersion, appData.c_str(), context.device.Get());
    if (!succeeded(init)) {
        std::wcerr << L"stream ngx_init=0x" << std::hex << static_cast<unsigned int>(init) << L"\n";
        std::wcerr << L"stream NGX initialization failed\n";
        return 1;
    }
    NVSDK_NGX_Parameter* parameters = nullptr;
    NVSDK_NGX_Result caps = NVSDK_NGX_D3D12_GetCapabilityParameters(&parameters);
    int available = 0;
    if (!succeeded(caps) || !parameters || !succeeded(parameters->Get(NVSDK_NGX_Parameter_SuperSampling_Available, &available)) || !available) {
        if (parameters) NVSDK_NGX_D3D12_DestroyParameters(parameters);
        NVSDK_NGX_D3D12_Shutdown1(context.device.Get());
        std::wcerr << L"stream resource creation failed\n";
        return 1;
    }
    Texture color, motion, depth, output;
    if (!createTexture(context, inputWidth, inputHeight, DXGI_FORMAT_R16G16B16A16_FLOAT, D3D12_RESOURCE_FLAG_NONE,
                       D3D12_RESOURCE_STATE_COPY_DEST, color) ||
        !createTexture(context, inputWidth, inputHeight, DXGI_FORMAT_R32_FLOAT, D3D12_RESOURCE_FLAG_NONE,
                       D3D12_RESOURCE_STATE_COPY_DEST, depth) ||
        !createTexture(context, inputWidth, inputHeight, DXGI_FORMAT_R16G16_FLOAT, D3D12_RESOURCE_FLAG_NONE,
                       D3D12_RESOURCE_STATE_COPY_DEST, motion) ||
        !createTexture(context, outputWidth, outputHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
                       D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, output)) return 1;
    std::vector<unsigned char> depthBytes(static_cast<size_t>(inputWidth) * inputHeight * sizeof(float));
    std::fill(reinterpret_cast<float*>(depthBytes.data()),
              reinterpret_cast<float*>(depthBytes.data()) + static_cast<size_t>(inputWidth) * inputHeight, 1.0f);
    context.list->Close();
    context.allocator->Reset();
    context.list->Reset(context.allocator.Get(), nullptr);
    std::vector<ComPtr<ID3D12Resource>> uploads;
    if (!uploadTexture(context, depth, depthBytes, uploads)) { std::wcerr << L"stream depth upload failed\n"; return 1; }
    D3D12_RESOURCE_BARRIER depthBarrier{};
    depthBarrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    depthBarrier.Transition.pResource = depth.resource.Get();
    depthBarrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    depthBarrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    depthBarrier.Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    context.list->ResourceBarrier(1, &depthBarrier);
    if (!context.submit()) { std::wcerr << L"stream depth submit failed\n"; return 1; }

    context.allocator->Reset();
    context.list->Reset(context.allocator.Get(), nullptr);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_Width, inputWidth);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_Height, inputHeight);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_OutWidth, outputWidth);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_OutHeight, outputHeight);
    NVSDK_NGX_Parameter_SetI(parameters, NVSDK_NGX_Parameter_PerfQualityValue, perf);
    NVSDK_NGX_Parameter_SetI(parameters, NVSDK_NGX_Parameter_DLSS_Feature_Create_Flags, NVSDK_NGX_DLSS_Feature_Flags_None);
    NVSDK_NGX_Parameter_SetI(parameters, NVSDK_NGX_Parameter_DLSSMode, NVSDK_NGX_DLSS_Mode_DLSS);
    const char* presetParameter = perf == NVSDK_NGX_PerfQuality_Value_DLAA ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_DLAA :
        perf == NVSDK_NGX_PerfQuality_Value_Balanced ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Balanced :
        perf == NVSDK_NGX_PerfQuality_Value_MaxPerf ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Performance :
        perf == NVSDK_NGX_PerfQuality_Value_UltraPerformance ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraPerformance :
        perf == NVSDK_NGX_PerfQuality_Value_UltraQuality ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraQuality :
        NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Quality;
    NVSDK_NGX_Parameter_SetI(parameters, presetParameter, preset);
    NVSDK_NGX_Handle* feature = nullptr;
    NVSDK_NGX_Result create = NVSDK_NGX_D3D12_CreateFeature(context.list.Get(), NVSDK_NGX_Feature_SuperSampling, parameters, &feature);
    std::wcerr << L"stream feature_create=0x" << std::hex << static_cast<unsigned int>(create) << std::dec << L"\n";
    if (!succeeded(create) || !feature) return 1;
    if (!context.submit()) { std::wcerr << L"stream feature submit failed\n"; return 1; }

    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    const size_t maxColorBytes = static_cast<size_t>(inputWidth) * inputHeight * 4;
    const size_t maxMotionBytes = static_cast<size_t>(inputWidth) * inputHeight * sizeof(float) * 2;
    uint32_t expectedFrame = 0;
    for (;;) {
        StreamInputHeader header{};
        if (!readExact(&header, sizeof(header))) break;
        if (header.magic != kStreamInputMagic || header.frame != expectedFrame || header.width != inputWidth || header.height != inputHeight ||
            header.colorBytes != maxColorBytes || (header.motionBytes != 0 && header.motionBytes != maxMotionBytes)) return 3;
        std::vector<unsigned char> rgba(header.colorBytes);
        std::vector<unsigned char> motionFloats(header.motionBytes);
        if (!readExact(rgba.data(), rgba.size()) || (header.motionBytes && !readExact(motionFloats.data(), motionFloats.size()))) return 3;
        std::vector<unsigned char> colorBytes(static_cast<size_t>(inputWidth) * inputHeight * 8);
        auto* halfColor = reinterpret_cast<uint16_t*>(colorBytes.data());
        for (size_t i = 0; i < static_cast<size_t>(inputWidth) * inputHeight; ++i)
            for (int channel = 0; channel < 4; ++channel) halfColor[i * 4 + channel] = floatToHalf(rgba[i * 4 + channel] / 255.0f);
        std::vector<unsigned char> halfMotion(static_cast<size_t>(inputWidth) * inputHeight * 4);
        const float* motionData = reinterpret_cast<const float*>(motionFloats.data());
        auto* halfMv = reinterpret_cast<uint16_t*>(halfMotion.data());
        for (size_t i = 0; i < static_cast<size_t>(inputWidth) * inputHeight; ++i) {
            halfMv[i * 2] = floatToHalf(header.motionBytes ? motionData[i * 2] : 0.0f);
            halfMv[i * 2 + 1] = floatToHalf(header.motionBytes ? motionData[i * 2 + 1] : 0.0f);
        }
        context.allocator->Reset();
        context.list->Reset(context.allocator.Get(), nullptr);
        D3D12_RESOURCE_BARRIER before[3]{};
        before[0].Type = before[1].Type = before[2].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        before[0].Transition = {color.resource.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST};
        before[1].Transition = {motion.resource.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST};
        before[2].Transition = {output.resource.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                                D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
        if (header.frame == 0) {
            // Color, motion, and output are already in their initial states.
        } else {
            context.list->ResourceBarrier(3, before);
        }
        uploads.clear();
        if (!uploadTexture(context, color, colorBytes, uploads) || !uploadTexture(context, motion, halfMotion, uploads)) {
            std::wcerr << L"stream frame upload failed\n";
            return 1;
        }
        D3D12_RESOURCE_BARRIER after[2]{};
        after[0].Type = after[1].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        after[0].Transition = {color.resource.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                               D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
        after[1].Transition = {motion.resource.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                               D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
        context.list->ResourceBarrier(2, after);
        NVSDK_NGX_Parameter_SetD3d12Resource(parameters, NVSDK_NGX_Parameter_Color, color.resource.Get());
        NVSDK_NGX_Parameter_SetD3d12Resource(parameters, NVSDK_NGX_Parameter_Output, output.resource.Get());
        NVSDK_NGX_Parameter_SetD3d12Resource(parameters, NVSDK_NGX_Parameter_Depth, depth.resource.Get());
        NVSDK_NGX_Parameter_SetD3d12Resource(parameters, NVSDK_NGX_Parameter_MotionVectors, motion.resource.Get());
        NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_Jitter_Offset_X, 0.0f);
        NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_Jitter_Offset_Y, 0.0f);
        NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_MV_Scale_X, 1.0f);
        NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_MV_Scale_Y, 1.0f);
        NVSDK_NGX_Parameter_SetI(parameters, NVSDK_NGX_Parameter_Reset, header.reset ? 1 : 0);
        NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_DLSS_Pre_Exposure, 1.0f);
        NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_DLSS_Exposure_Scale, 1.0f);
        NVSDK_NGX_Result evaluate = NVSDK_NGX_D3D12_EvaluateFeature_C(context.list.Get(), feature, parameters, nullptr);
        D3D12_RESOURCE_BARRIER outputBarrier{};
        outputBarrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        outputBarrier.Transition = {output.resource.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                                    D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE};
        context.list->ResourceBarrier(1, &outputBarrier);
        std::vector<unsigned char> outputBytes;
        if (!succeeded(evaluate)) { std::wcerr << L"stream evaluate=0x" << std::hex << static_cast<unsigned int>(evaluate) << std::dec << L"\n"; return 1; }
        if (!readbackTexture(context, output, outputBytes)) { std::wcerr << L"stream readback failed\n"; return 1; }
        std::vector<unsigned char> outputRgba = rgbaFromHalf(outputBytes);
        StreamOutputHeader response{kStreamOutputMagic, header.frame, outputWidth, outputHeight,
                                    succeeded(evaluate) ? 0u : static_cast<uint32_t>(evaluate),
                                    static_cast<uint32_t>(outputRgba.size())};
        if (!writeExact(&response, sizeof(response)) || !writeExact(outputRgba.data(), outputRgba.size())) return 4;
        std::cout.flush();
        expectedFrame = header.frame + 1;
        (void)expectedFrame;
    }
    NVSDK_NGX_D3D12_ReleaseFeature(feature);
    NVSDK_NGX_D3D12_DestroyParameters(parameters);
    NVSDK_NGX_D3D12_Shutdown1(context.device.Get());
    return 0;
}
}

int wmain(int argc, wchar_t** argv)
{
    if (argc >= 2 && std::wstring(argv[1]) == L"stream") {
        if (argc < 6) {
            std::wcerr << L"usage: dlss_sr_host.exe stream <input_w> <input_h> <output_w> <output_h> [mode] [preset]\n";
            return 2;
        }
        const UINT inputWidth = static_cast<UINT>(wcstoul(argv[2], nullptr, 10));
        const UINT inputHeight = static_cast<UINT>(wcstoul(argv[3], nullptr, 10));
        const UINT outputWidth = static_cast<UINT>(wcstoul(argv[4], nullptr, 10));
        const UINT outputHeight = static_cast<UINT>(wcstoul(argv[5], nullptr, 10));
        std::wstring mode = argc >= 7 ? argv[6] : L"quality";
        NVSDK_NGX_PerfQuality_Value perf = mode == L"dlaa" ? NVSDK_NGX_PerfQuality_Value_DLAA :
            mode == L"balanced" ? NVSDK_NGX_PerfQuality_Value_Balanced : mode == L"performance" ? NVSDK_NGX_PerfQuality_Value_MaxPerf :
            mode == L"ultraperformance" ? NVSDK_NGX_PerfQuality_Value_UltraPerformance : NVSDK_NGX_PerfQuality_Value_MaxQuality;
        int preset = NVSDK_NGX_DLSS_Hint_Render_Preset_Default;
        if (argc >= 8) {
            std::wstring presetArg = argv[7];
            if (presetArg == L"J") preset = NVSDK_NGX_DLSS_Hint_Render_Preset_J;
            else if (presetArg == L"K") preset = NVSDK_NGX_DLSS_Hint_Render_Preset_K;
            else if (presetArg == L"L") preset = NVSDK_NGX_DLSS_Hint_Render_Preset_L;
            else if (presetArg == L"M") preset = NVSDK_NGX_DLSS_Hint_Render_Preset_M;
        }
        return runStream(fs::absolute(fs::path(argv[0])).parent_path(), inputWidth, inputHeight,
                         outputWidth, outputHeight, perf, preset);
    }
    if (argc < 2 || std::wstring(argv[1]) != L"selftest") {
        std::wcerr << L"usage: dlss_sr_host.exe selftest [dlaa]\n";
        return 2;
    }
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) {
        std::wcerr << L"COM initialization failed\n";
        return 1;
    }

    fs::path root = fs::absolute(fs::path(argv[0])).parent_path();
    std::wstring mode = argc >= 3 ? argv[2] : L"quality";
    NVSDK_NGX_PerfQuality_Value perf = NVSDK_NGX_PerfQuality_Value_MaxQuality;
    if (mode == L"dlaa") perf = NVSDK_NGX_PerfQuality_Value_DLAA;
    else if (mode == L"balanced") perf = NVSDK_NGX_PerfQuality_Value_Balanced;
    else if (mode == L"performance") perf = NVSDK_NGX_PerfQuality_Value_MaxPerf;
    else if (mode == L"ultraperformance") perf = NVSDK_NGX_PerfQuality_Value_UltraPerformance;
    else if (mode == L"ultraquality") perf = NVSDK_NGX_PerfQuality_Value_UltraQuality;
    else mode = L"quality";
    const bool dlaa = mode == L"dlaa";
    const char* modeName = mode == L"dlaa" ? "DLAA" : mode == L"balanced" ? "Balanced" :
                           mode == L"performance" ? "Performance" : mode == L"ultraperformance" ? "Ultra Performance" :
                           mode == L"ultraquality" ? "Ultra Quality" : "Quality";
    const std::wstring presetArg = argc >= 4 ? argv[3] : L"default";
    int preset = NVSDK_NGX_DLSS_Hint_Render_Preset_Default;
    if (presetArg == L"J") preset = NVSDK_NGX_DLSS_Hint_Render_Preset_J;
    else if (presetArg == L"K") preset = NVSDK_NGX_DLSS_Hint_Render_Preset_K;
    else if (presetArg == L"L") preset = NVSDK_NGX_DLSS_Hint_Render_Preset_L;
    else if (presetArg == L"M") preset = NVSDK_NGX_DLSS_Hint_Render_Preset_M;
    fs::path appData = root / "ngx-data";
    fs::create_directories(appData);

    Context context;
    if (!context.initialize()) {
        std::cerr << "D3D12 initialization failed\n";
        return 1;
    }

    NVSDK_NGX_Result init = NVSDK_NGX_D3D12_Init_with_ProjectID(
        kProjectId, NVSDK_NGX_ENGINE_TYPE_CUSTOM, kEngineVersion,
        appData.c_str(), context.device.Get());
    std::wcerr << L"ngx_init=0x" << std::hex << static_cast<unsigned int>(init) << std::dec
               << L" (" << resultName(init) << L")\n";
    if (!succeeded(init)) return 1;

    NVSDK_NGX_Parameter* parameters = nullptr;
    NVSDK_NGX_Result caps = NVSDK_NGX_D3D12_GetCapabilityParameters(&parameters);
    std::wcerr << L"ngx_capability_parameters=0x" << std::hex << static_cast<unsigned int>(caps)
               << std::dec << L" (" << resultName(caps) << L")\n";
    if (!succeeded(caps)) {
        NVSDK_NGX_D3D12_Shutdown1(context.device.Get());
        return 1;
    }

    int available = 0;
    NVSDK_NGX_Result availableResult = parameters->Get(
        NVSDK_NGX_Parameter_SuperSampling_Available, &available);
    std::wcerr << L"super_sampling_available_result=0x" << std::hex
               << static_cast<unsigned int>(availableResult) << std::dec << L" ("
               << resultName(availableResult) << L") value=" << available << L"\n";

    if (!succeeded(availableResult) || !available) {
        NVSDK_NGX_D3D12_DestroyParameters(parameters);
        NVSDK_NGX_D3D12_Shutdown1(context.device.Get());
        return 1;
    }

    const UINT outputWidth = dlaa ? 640 : 960;
    const UINT outputHeight = dlaa ? 360 : 540;
    UINT inputWidth = dlaa ? 640 : 640;
    UINT inputHeight = dlaa ? 360 : 360;
    unsigned int maxWidth = 0, maxHeight = 0, minWidth = 0, minHeight = 0;
    float sharpness = 0.0f;
    NVSDK_NGX_Result optimal = NGX_DLSS_GET_OPTIMAL_SETTINGS(
        parameters, outputWidth, outputHeight, perf, &inputWidth, &inputHeight,
        &maxWidth, &maxHeight, &minWidth, &minHeight, &sharpness);
    std::wcerr << L"optimal_settings=0x" << std::hex << static_cast<unsigned int>(optimal) << std::dec
               << L" (" << resultName(optimal) << L") render=" << inputWidth << L"x" << inputHeight
               << L" output=" << outputWidth << L"x" << outputHeight << L"\n";
    if (!succeeded(optimal) || inputWidth == 0 || inputHeight == 0) {
        NVSDK_NGX_D3D12_DestroyParameters(parameters);
        NVSDK_NGX_D3D12_Shutdown1(context.device.Get());
        return 1;
    }
    const auto inputBytes = syntheticColor(inputWidth, inputHeight);
    fs::path selftestDir = root / "selftest";
    fs::create_directories(selftestDir);
    if (!writePng(selftestDir / "input.png", inputWidth, inputHeight, rgbaFromHalf(inputBytes))) {
        std::wcerr << L"failed to write input.png\n";
        CoUninitialize();
        return 1;
    }

    Texture color, depth, motion, output;
    if (!createTexture(context, inputWidth, inputHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
                       D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST, color) ||
        !createTexture(context, inputWidth, inputHeight, DXGI_FORMAT_R32_FLOAT,
                       D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST, depth) ||
        !createTexture(context, inputWidth, inputHeight, DXGI_FORMAT_R16G16_FLOAT,
                       D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST, motion) ||
        !createTexture(context, outputWidth, outputHeight, DXGI_FORMAT_R16G16B16A16_FLOAT,
                       D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, output)) {
        NVSDK_NGX_D3D12_DestroyParameters(parameters);
        NVSDK_NGX_D3D12_Shutdown1(context.device.Get());
        return 1;
    }

    std::vector<unsigned char> depthBytes(static_cast<size_t>(inputWidth) * inputHeight * sizeof(float));
    std::fill(reinterpret_cast<float*>(depthBytes.data()),
              reinterpret_cast<float*>(depthBytes.data()) + static_cast<size_t>(inputWidth) * inputHeight, 1.0f);
    std::vector<unsigned char> motionBytes(static_cast<size_t>(inputWidth) * inputHeight * sizeof(uint32_t));
    std::vector<ComPtr<ID3D12Resource>> uploads;
    context.list->Close();
    context.allocator->Reset();
    context.list->Reset(context.allocator.Get(), nullptr);
    if (!uploadTexture(context, color, inputBytes, uploads) ||
        !uploadTexture(context, depth, depthBytes, uploads) ||
        !uploadTexture(context, motion, motionBytes, uploads)) return 1;
    D3D12_RESOURCE_BARRIER barriers[3]{};
    for (int i = 0; i < 3; ++i) {
        barriers[i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barriers[i].Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barriers[i].Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
        barriers[i].Transition.StateAfter = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    }
    barriers[0].Transition.pResource = color.resource.Get();
    barriers[1].Transition.pResource = depth.resource.Get();
    barriers[2].Transition.pResource = motion.resource.Get();
    context.list->ResourceBarrier(3, barriers);
    if (!context.submit()) return 1;

    context.allocator->Reset();
    context.list->Reset(context.allocator.Get(), nullptr);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_Width, inputWidth);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_Height, inputHeight);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_OutWidth, outputWidth);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_OutHeight, outputHeight);
    NVSDK_NGX_Parameter_SetI(parameters, NVSDK_NGX_Parameter_PerfQualityValue,
                              perf);
    NVSDK_NGX_Parameter_SetI(parameters, NVSDK_NGX_Parameter_DLSS_Feature_Create_Flags,
                              NVSDK_NGX_DLSS_Feature_Flags_None);
    NVSDK_NGX_Parameter_SetI(parameters, NVSDK_NGX_Parameter_DLSSMode, NVSDK_NGX_DLSS_Mode_DLSS);
    const char* presetParameter = dlaa ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_DLAA :
        mode == L"balanced" ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Balanced :
        mode == L"performance" ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Performance :
        mode == L"ultraperformance" ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraPerformance :
        mode == L"ultraquality" ? NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraQuality :
        NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Quality;
    NVSDK_NGX_Parameter_SetI(parameters, presetParameter, preset);

    NVSDK_NGX_Handle* feature = nullptr;
    NVSDK_NGX_Result create = NVSDK_NGX_D3D12_CreateFeature(
        context.list.Get(), NVSDK_NGX_Feature_SuperSampling, parameters, &feature);
    std::wcerr << L"feature_create=0x" << std::hex << static_cast<unsigned int>(create) << std::dec
               << L" (" << resultName(create) << L")\n";
    if (!succeeded(create) || !feature) {
        NVSDK_NGX_D3D12_DestroyParameters(parameters);
        NVSDK_NGX_D3D12_Shutdown1(context.device.Get());
        return 1;
    }

    NVSDK_NGX_Parameter_SetD3d12Resource(parameters, NVSDK_NGX_Parameter_Color, color.resource.Get());
    NVSDK_NGX_Parameter_SetD3d12Resource(parameters, NVSDK_NGX_Parameter_Output, output.resource.Get());
    NVSDK_NGX_Parameter_SetD3d12Resource(parameters, NVSDK_NGX_Parameter_Depth, depth.resource.Get());
    NVSDK_NGX_Parameter_SetD3d12Resource(parameters, NVSDK_NGX_Parameter_MotionVectors, motion.resource.Get());
    NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_Jitter_Offset_X, 0.0f);
    NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_Jitter_Offset_Y, 0.0f);
    NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_MV_Scale_X, 1.0f);
    NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_MV_Scale_Y, 1.0f);
    NVSDK_NGX_Parameter_SetI(parameters, NVSDK_NGX_Parameter_Reset, 1);
    NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_DLSS_Pre_Exposure, 1.0f);
    NVSDK_NGX_Parameter_SetF(parameters, NVSDK_NGX_Parameter_DLSS_Exposure_Scale, 1.0f);

    const auto start = std::chrono::steady_clock::now();
    NVSDK_NGX_Result evaluate = NVSDK_NGX_D3D12_EvaluateFeature_C(context.list.Get(), feature, parameters, nullptr);
    std::wcerr << L"feature_evaluate=0x" << std::hex << static_cast<unsigned int>(evaluate) << std::dec
               << L" (" << resultName(evaluate) << L")\n";
    D3D12_RESOURCE_BARRIER outputBarrier{};
    outputBarrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    outputBarrier.Transition.pResource = output.resource.Get();
    outputBarrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    outputBarrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    outputBarrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    context.list->ResourceBarrier(1, &outputBarrier);
    std::vector<unsigned char> outputBytes;
    bool copied = succeeded(evaluate) && readbackTexture(context, output, outputBytes);
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start).count();
    NVSDK_NGX_D3D12_ReleaseFeature(feature);
    NVSDK_NGX_D3D12_DestroyParameters(parameters);
    NVSDK_NGX_D3D12_Shutdown1(context.device.Get());

    const fs::path outputPath = selftestDir / (dlaa ? "output_dlaa.png" : "output_quality.png");
    if (!copied || !writePng(outputPath, outputWidth, outputHeight, rgbaFromHalf(outputBytes))) {
        CoUninitialize();
        return 1;
    }
    std::ofstream result(selftestDir / "result.json");
    result << "{\n  \"status\": \"success\",\n  \"ngx_initialized\": true,\n"
           << "  \"super_sampling_available\": true,\n  \"feature_created\": true,\n"
           << "  \"evaluate_succeeded\": true,\n  \"input\": [640, 360],\n"
           << "  \"output\": [" << outputWidth << ", " << outputHeight << "],\n  \"mode\": \""
           << modeName << "\",\n"
           << "  \"elapsed_ms\": " << elapsed << "\n}\n";
    result.close();
    std::cout << "{\"status\":\"success\",\"feature_created\":true,\"evaluate_succeeded\":true}\n";
    CoUninitialize();
    return 0;
}
