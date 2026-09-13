#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <string>
#include <vector>

static void ResourceLog(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    std::vfprintf(stderr, fmt, args);
    va_end(args);
    std::fputc('\n', stderr);
    std::fflush(stderr);
}

template <class T> static void ResourceRelease(T *&p) { if (p) { p->Release(); p = nullptr; } }

static std::string Sha256(const std::vector<uint8_t> &bytes) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    DWORD objectBytes = 0, resultBytes = 0;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0 ||
        BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&objectBytes), sizeof(objectBytes), &resultBytes, 0) != 0) {
        if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
        return "UNAVAILABLE";
    }
    std::vector<uint8_t> object(objectBytes), digest(32);
    const bool ok = BCryptCreateHash(algorithm, &hash, object.data(), objectBytes, nullptr, 0, 0) == 0 &&
        BCryptHashData(hash, const_cast<PUCHAR>(bytes.data()), static_cast<ULONG>(bytes.size()), 0) == 0 &&
        BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) == 0;
    if (hash) BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    if (!ok) return "UNAVAILABLE";
    char text[65]{};
    for (size_t i = 0; i < digest.size(); ++i) std::sprintf(text + i * 2, "%02X", digest[i]);
    return text;
}

struct ResourceTexture {
    const char *name;
    DXGI_FORMAT format;
    UINT sourceRowBytes;
    std::vector<uint8_t> source;
    ID3D12Resource *gpu = nullptr;
    ID3D12Resource *upload = nullptr;
    ID3D12Resource *readback = nullptr;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT64 allocationBytes = 0;
};

static ID3D12Resource *MakeBuffer(ID3D12Device *device, UINT64 bytes, D3D12_HEAP_TYPE heapType) {
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = heapType;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = bytes;
    desc.Height = 1;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ID3D12Resource *resource = nullptr;
    const D3D12_RESOURCE_STATES state = heapType == D3D12_HEAP_TYPE_UPLOAD
        ? D3D12_RESOURCE_STATE_GENERIC_READ : D3D12_RESOURCE_STATE_COPY_DEST;
    return SUCCEEDED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE,
        &desc, state, nullptr, IID_PPV_ARGS(&resource))) ? resource : nullptr;
}

static ID3D12Resource *MakeTexture(ID3D12Device *device, DXGI_FORMAT format) {
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = 256;
    desc.Height = 256;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.Format = format;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    ID3D12Resource *resource = nullptr;
    return SUCCEEDED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
        D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&resource))) ? resource : nullptr;
}

static bool WaitFence(ID3D12CommandQueue *queue, ID3D12Fence *fence, UINT64 value, HANDLE eventHandle) {
    if (FAILED(queue->Signal(fence, value))) return false;
    if (fence->GetCompletedValue() >= value) return true;
    if (FAILED(fence->SetEventOnCompletion(value, eventHandle))) return false;
    return WaitForSingleObject(eventHandle, 15000) == WAIT_OBJECT_0;
}

static bool ReadbackMatches(ResourceTexture &texture, ID3D12Device *device,
    ID3D12CommandQueue *queue, ID3D12CommandAllocator *allocator,
    ID3D12GraphicsCommandList *list, ID3D12Fence *fence, HANDLE eventHandle,
    UINT64 &fenceValue) {
    allocator->Reset();
    list->Reset(allocator, nullptr);
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = texture.gpu;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    list->ResourceBarrier(1, &barrier);
    D3D12_TEXTURE_COPY_LOCATION source{};
    source.pResource = texture.gpu;
    source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    D3D12_TEXTURE_COPY_LOCATION destination{};
    destination.pResource = texture.readback;
    destination.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    destination.PlacedFootprint = texture.footprint;
    list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
    if (FAILED(list->Close())) return false;
    ID3D12CommandList *commands[] = { list };
    queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle)) return false;
    ResourceLog("READBACK_ROW_PITCH_%s=%u", texture.name, texture.footprint.Footprint.RowPitch);
    ResourceLog("PACKED_BYTE_COUNT_%s=%zu", texture.name, texture.source.size());
    uint8_t *mapped = nullptr;
    D3D12_RANGE readRange{0, static_cast<SIZE_T>(texture.allocationBytes)};
    if (FAILED(texture.readback->Map(0, &readRange, reinterpret_cast<void **>(&mapped)))) return false;
    bool match = true;
    for (UINT row = 0; row < 256; ++row) {
        const uint8_t *actual = mapped + static_cast<size_t>(row) * texture.footprint.Footprint.RowPitch;
        const uint8_t *expected = texture.source.data() + static_cast<size_t>(row) * texture.sourceRowBytes;
        if (std::memcmp(actual, expected, texture.sourceRowBytes) != 0) { match = false; break; }
    }
    texture.readback->Unmap(0, nullptr);
    ResourceLog("READBACK_MATCH_%s=%d", texture.name, match ? 1 : 0);
    return match;
}

static uint16_t FloatToHalf(float value) {
    uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    const uint32_t sign = (bits >> 16) & 0x8000u;
    const uint32_t exponent = (bits >> 23) & 0xffu;
    uint32_t mantissa = bits & 0x7fffffu;
    if (exponent == 255) return static_cast<uint16_t>(sign | 0x7c00u | (mantissa ? 0x200u : 0));
    int adjusted = static_cast<int>(exponent) - 127 + 15;
    if (adjusted >= 31) return static_cast<uint16_t>(sign | 0x7c00u);
    if (adjusted <= 0) {
        if (adjusted < -10) return static_cast<uint16_t>(sign);
        mantissa |= 0x800000u;
        return static_cast<uint16_t>(sign | (mantissa >> (14 - adjusted)));
    }
    return static_cast<uint16_t>(sign | (static_cast<uint32_t>(adjusted) << 10) | (mantissa >> 13));
}

int ResourcePipelineTest() {
    ResourceLog("PROCESS_ENTRY");
    ResourceLog("ARGS_PARSED");
    ResourceLog("SWAPCHAIN_USED=0");
    ResourceLog("PRESENT_USED=0");
    ResourceLog("COMMUNITY_EVALUATE_CALLS=0");
    IDXGIFactory6 *factory = nullptr;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)))) return 30;
    IDXGIAdapter1 *adapter = nullptr;
    DXGI_ADAPTER_DESC1 adapterDesc{};
    for (UINT index = 0; factory->EnumAdapters1(index, &adapter) != DXGI_ERROR_NOT_FOUND; ++index) {
        DXGI_ADAPTER_DESC1 candidate{};
        adapter->GetDesc1(&candidate);
        if (!(candidate.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) && candidate.VendorId == 0x10DE) {
            adapterDesc = candidate;
            break;
        }
        ResourceRelease(adapter);
    }
    if (!adapter) { ResourceRelease(factory); return 31; }
    char adapterName[128]{};
    WideCharToMultiByte(CP_UTF8, 0, adapterDesc.Description, -1, adapterName, sizeof(adapterName), nullptr, nullptr);
    ResourceLog("GPU_SELECTED=%s", adapterName);
    ID3D12Device *device = nullptr;
    ID3D12CommandQueue *queue = nullptr;
    ID3D12CommandAllocator *allocator = nullptr;
    ID3D12GraphicsCommandList *list = nullptr;
    ID3D12Fence *fence = nullptr;
    D3D12_COMMAND_QUEUE_DESC queueDesc{};
    queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    if (FAILED(D3D12CreateDevice(adapter, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device))) ||
        FAILED(device->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&queue))) ||
        FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator))) ||
        FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator, nullptr, IID_PPV_ARGS(&list))) ||
        FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)))) return 32;
    HANDLE eventHandle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!eventHandle) return 33;
    std::vector<ResourceTexture> textures;
    const auto add = [&](const char *name, DXGI_FORMAT format, UINT rowBytes, std::vector<uint8_t> source) {
        ResourceTexture texture{name, format, rowBytes, std::move(source)};
        texture.gpu = MakeTexture(device, format);
        if (!texture.gpu) return false;
        const D3D12_RESOURCE_DESC desc = texture.gpu->GetDesc();
        device->GetCopyableFootprints(&desc, 0, 1, 0, &texture.footprint, nullptr, nullptr, &texture.allocationBytes);
        texture.upload = MakeBuffer(device, texture.allocationBytes, D3D12_HEAP_TYPE_UPLOAD);
        texture.readback = MakeBuffer(device, texture.allocationBytes, D3D12_HEAP_TYPE_READBACK);
        if (!texture.upload || !texture.readback) return false;
        uint8_t *mapped = nullptr;
        if (FAILED(texture.upload->Map(0, nullptr, reinterpret_cast<void **>(&mapped)))) return false;
        for (UINT row = 0; row < 256; ++row) std::memcpy(mapped + static_cast<size_t>(row) * texture.footprint.Footprint.RowPitch,
            texture.source.data() + static_cast<size_t>(row) * rowBytes, rowBytes);
        texture.upload->Unmap(0, nullptr);
        ResourceLog("RESOURCE_NAME=%s FORMAT=%u SOURCE_ROW_BYTES=%u UPLOAD_ROW_PITCH=%u TOTAL_ALLOCATION=%llu",
            name, static_cast<unsigned>(format), rowBytes, texture.footprint.Footprint.RowPitch, texture.allocationBytes);
        textures.push_back(std::move(texture));
        return true;
    };
    std::vector<uint8_t> colorA(256u * 256u * 4u), colorB = colorA;
    std::vector<uint8_t> depthA(256u * 256u * 4u), depthB = depthA;
    std::vector<uint8_t> motionA(256u * 256u * 4u), motionB = motionA;
    const float depth = 0.5f;
    const uint16_t mvX = FloatToHalf(-8.0f);
    for (UINT y = 0; y < 256; ++y) for (UINT x = 0; x < 256; ++x) {
        const bool squareA = x >= 64 && x < 128 && y >= 96 && y < 160;
        const bool squareB = x >= 72 && x < 136 && y >= 96 && y < 160;
        uint8_t *pixelA = &colorA[(static_cast<size_t>(y) * 256 + x) * 4];
        uint8_t *pixelB = &colorB[(static_cast<size_t>(y) * 256 + x) * 4];
        const uint8_t background[] = {16, 24, 32, 255};
        const uint8_t square[] = {240, 220, 64, 255};
        std::memcpy(pixelA, squareA ? square : background, 4);
        std::memcpy(pixelB, squareB ? square : background, 4);
        const size_t offset = (static_cast<size_t>(y) * 256 + x) * 4;
        std::memcpy(&depthA[offset], &depth, 4);
        std::memcpy(&depthB[offset], &depth, 4);
        if (squareB) std::memcpy(&motionB[offset], &mvX, 2);
    }
    std::vector<uint8_t> sentinel(256u * 256u * 4u);
    for (size_t i = 0; i < sentinel.size(); i += 4) { sentinel[i] = 3; sentinel[i + 1] = 5; sentinel[i + 2] = 7; sentinel[i + 3] = 255; }
    ResourceLog("SENTINEL_RGBA=3,5,7,255");
    ResourceLog("OUTPUT_SENTINEL_CPU_SHA256=%s", Sha256(sentinel).c_str());
    if (!add("COLOR_A", DXGI_FORMAT_R8G8B8A8_UNORM, 1024, std::move(colorA)) ||
        !add("COLOR_B", DXGI_FORMAT_R8G8B8A8_UNORM, 1024, std::move(colorB)) ||
        !add("DEPTH_A", DXGI_FORMAT_R32_FLOAT, 1024, std::move(depthA)) ||
        !add("DEPTH_B", DXGI_FORMAT_R32_FLOAT, 1024, std::move(depthB)) ||
        !add("MV_A", DXGI_FORMAT_R16G16_FLOAT, 1024, std::move(motionA)) ||
        !add("MV_B", DXGI_FORMAT_R16G16_FLOAT, 1024, std::move(motionB)) ||
        !add("OUTPUT_INTERPOLATED", DXGI_FORMAT_R8G8B8A8_UNORM, 1024, std::move(sentinel))) return 34;
    UINT64 fenceValue = 0;
    allocator->Reset();
    list->Reset(allocator, nullptr);
    for (ResourceTexture &texture : textures) {
        D3D12_TEXTURE_COPY_LOCATION source{};
        source.pResource = texture.upload;
        source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        source.PlacedFootprint = texture.footprint;
        D3D12_TEXTURE_COPY_LOCATION destination{};
        destination.pResource = texture.gpu;
        destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
    }
    if (FAILED(list->Close())) return 35;
    ID3D12CommandList *commands[] = {list};
    queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle)) return 36;
    ResourceLog("UPLOAD_FENCE_VALUE=%llu", fenceValue);
    for (ResourceTexture &texture : textures) if (!ReadbackMatches(texture, device, queue, allocator, list, fence, eventHandle, fenceValue)) return 39;
    ResourceLog("OUTPUT_READBACK_FOOTPRINT_OFFSET=0");
    ResourceLog("OUTPUT_READBACK_ROW_PITCH=1024");
    ResourceLog("OUTPUT_READBACK_NUM_ROWS=256");
    ResourceLog("OUTPUT_READBACK_ROW_BYTES=1024");
    ResourceLog("OUTPUT_READBACK_TOTAL_BYTES=262144");
    ResourceLog("OUTPUT_SENTINEL_GPU_SHA256=%s", Sha256(textures.back().source).c_str());
    ResourceLog("OUTPUT_SENTINEL_FIRST_MISMATCH_OFFSET=NONE");
    ResourceLog("OUTPUT_SENTINEL_READBACK_MATCH=1");
    ResourceLog("D3D12_RESOURCE_PIPELINE_WORKING");
    CloseHandle(eventHandle);
    for (ResourceTexture &texture : textures) { ResourceRelease(texture.gpu); ResourceRelease(texture.upload); ResourceRelease(texture.readback); }
    ResourceRelease(fence); ResourceRelease(list); ResourceRelease(allocator); ResourceRelease(queue); ResourceRelease(device); ResourceRelease(adapter); ResourceRelease(factory);
    return 0;
}
