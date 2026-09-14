#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <nvapi.h>
#include <nvsdk_ngx.h>
#include <nvsdk_ngx_defs_dlssg.h>
#include <nvsdk_ngx_params_dlssg.h>
#include "worker_protocol.h"
#include "nvof_d3d12.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

namespace fs = std::filesystem;
static constexpr UINT kWidth = 256, kHeight = 256, kRowBytes = kWidth * 4;
static constexpr char kSentinelSha[] = "1253466474BEA2C01580B221BDAF63E7428C17C5E6F96274A2403FB914B6E37C";

static void RunLog(const char *format, ...) {
    va_list args; va_start(args, format); std::vfprintf(stderr, format, args); va_end(args);
    std::fputc('\n', stderr); std::fflush(stderr);
}
template<class T> static void RunRelease(T *&p) { if (p) { p->Release(); p = nullptr; } }

using QueryFn = void *(__cdecl *)(uint32_t);
using NvInitFn = NvAPI_Status(__cdecl *)();
using NvEnumFn = NvAPI_Status(__cdecl *)(NvPhysicalGpuHandle *, NvU32 *);
using NvAdapterIdFn = NvAPI_Status(__cdecl *)(NvPhysicalGpuHandle, LUID *);
using NvArchFn = NvAPI_Status(__cdecl *)(NvPhysicalGpuHandle, NV_GPU_ARCH_INFO *);
using InitFn = NVSDK_NGX_Result (NVSDK_CONV *)(const char *, NVSDK_NGX_EngineType, const char *,
    const wchar_t *, ID3D12Device *, const NVSDK_NGX_FeatureCommonInfo *, NVSDK_NGX_Version);
using CreateFn = NVSDK_NGX_Result (NVSDK_CONV *)(ID3D12GraphicsCommandList *, NVSDK_NGX_Feature,
    const NVSDK_NGX_Parameter *, NVSDK_NGX_Handle **);
using EvalFn = NVSDK_NGX_Result (NVSDK_CONV *)(ID3D12GraphicsCommandList *, const NVSDK_NGX_Handle *,
    const NVSDK_NGX_Parameter *, PFN_NVSDK_NGX_ProgressCallback);
using ReleaseFeatureFn = NVSDK_NGX_Result (NVSDK_CONV *)(const NVSDK_NGX_Handle *);
// These are provider-internal exports, absent from the public SDK headers.
// Their argument order is established from the pinned DLL's x64 stubs:
// PopulateDeviceParameters(device, parameters), then PopulateParameters(parameters).
using PopulateParametersFn = NVSDK_NGX_Result (NVSDK_CONV *)(NVSDK_NGX_Parameter *);
using PopulateDeviceParametersFn = NVSDK_NGX_Result (NVSDK_CONV *)(ID3D12Device *, NVSDK_NGX_Parameter *);

struct Texture {
    const char *name = nullptr;
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    ID3D12Resource *gpu = nullptr, *upload = nullptr, *readback = nullptr;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT64 allocationBytes = 0;
    UINT width = 0, height = 0, rowBytes = 0;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
    std::vector<uint8_t> packed;
    uint8_t *mappedUpload = nullptr;
};
struct Buffer { ID3D12Resource *gpu = nullptr, *upload = nullptr, *readback = nullptr;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON; };

static void ReleaseTexture(Texture &texture) {
    if (texture.upload && texture.mappedUpload) texture.upload->Unmap(0, nullptr);
    RunRelease(texture.gpu); RunRelease(texture.upload); RunRelease(texture.readback);
    texture = {};
}
static void ReleaseBuffer(Buffer &buffer) {
    RunRelease(buffer.gpu); RunRelease(buffer.upload); RunRelease(buffer.readback);
    buffer = {};
}

static std::string Sha256(const std::vector<uint8_t> &bytes) {
    BCRYPT_ALG_HANDLE algorithm = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
    DWORD objectBytes = 0, resultBytes = 0;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0 ||
        BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&objectBytes),
            sizeof(objectBytes), &resultBytes, 0) != 0) {
        if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0); return "UNAVAILABLE";
    }
    std::vector<uint8_t> object(objectBytes); std::array<uint8_t, 32> digest{};
    const bool ok = BCryptCreateHash(algorithm, &hash, object.data(), objectBytes, nullptr, 0, 0) == 0 &&
        BCryptHashData(hash, const_cast<PUCHAR>(bytes.data()), static_cast<ULONG>(bytes.size()), 0) == 0 &&
        BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) == 0;
    if (hash) BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(algorithm, 0);
    if (!ok) return "UNAVAILABLE";
    char text[65]{}; for (size_t i = 0; i < digest.size(); ++i) std::snprintf(text + i * 2, 3, "%02X", digest[i]);
    return text;
}

static ID3D12Resource *MakeBuffer(ID3D12Device *device, UINT64 bytes, D3D12_HEAP_TYPE heapType,
    D3D12_RESOURCE_FLAGS flags, D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = heapType;
    D3D12_RESOURCE_DESC desc{}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; desc.Width = bytes;
    desc.Height = 1; desc.DepthOrArraySize = 1; desc.MipLevels = 1; desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR; desc.Flags = flags; ID3D12Resource *resource = nullptr;
    return SUCCEEDED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr,
        IID_PPV_ARGS(&resource))) ? resource : nullptr;
}

static bool MakeTexture(ID3D12Device *device, Texture &texture, const char *name, DXGI_FORMAT format,
    D3D12_RESOURCE_FLAGS flags, D3D12_RESOURCE_STATES initialState,
    UINT width = kWidth, UINT height = kHeight, UINT rowBytes = kRowBytes) {
    texture.name = name; texture.format = format; texture.state = initialState;
    texture.width = width; texture.height = height; texture.rowBytes = rowBytes;
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{}; desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = width; desc.Height = height; desc.DepthOrArraySize = 1; desc.MipLevels = 1;
    desc.Format = format; desc.SampleDesc.Count = 1; desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    desc.Flags = flags;
    if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, initialState, nullptr,
        IID_PPV_ARGS(&texture.gpu)))) return false;
    UINT rows = 0; UINT64 rowSize = 0;
    device->GetCopyableFootprints(&desc, 0, 1, 0, &texture.footprint, &rows, &rowSize,
        &texture.allocationBytes);
    texture.upload = MakeBuffer(device, texture.allocationBytes, D3D12_HEAP_TYPE_UPLOAD,
        D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_GENERIC_READ);
    texture.readback = MakeBuffer(device, texture.allocationBytes, D3D12_HEAP_TYPE_READBACK,
        D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST);
    texture.packed.resize(static_cast<size_t>(rowBytes) * height);
    if (FAILED(texture.upload->Map(0, nullptr, reinterpret_cast<void **>(&texture.mappedUpload)))) return false;
    RunLog("RESOURCE_CREATED name=%s ptr=%p format=%u width=%u height=%u rowPitch=%u initialState=0x%X",
        name, static_cast<void *>(texture.gpu), static_cast<unsigned>(format), width, height,
        texture.footprint.Footprint.RowPitch, static_cast<unsigned>(initialState));
    return texture.upload && texture.readback;
}

static void Transition(ID3D12GraphicsCommandList *list, ID3D12Resource *resource,
    D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
    if (before == after) return;
    D3D12_RESOURCE_BARRIER barrier{}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = resource; barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = before; barrier.Transition.StateAfter = after; list->ResourceBarrier(1, &barrier);
}

static bool ResetList(ID3D12CommandAllocator *allocator, ID3D12GraphicsCommandList *list,
    const char *stage) {
    const HRESULT ar = allocator->Reset(); if (FAILED(ar)) { RunLog("%s_ALLOCATOR_RESET_FAILED=0x%08X", stage, static_cast<unsigned>(ar)); return false; }
    const HRESULT lr = list->Reset(allocator, nullptr); if (FAILED(lr)) { RunLog("%s_LIST_RESET_FAILED=0x%08X", stage, static_cast<unsigned>(lr)); return false; }
    return true;
}

static bool WaitFence(ID3D12CommandQueue *queue, ID3D12Fence *fence, UINT64 value, HANDLE eventHandle,
    ID3D12Device *device, const char *stage) {
    const HRESULT sr = queue->Signal(fence, value); if (FAILED(sr)) { RunLog("%s_SIGNAL_FAILED=0x%08X", stage, static_cast<unsigned>(sr)); return false; }
    if (fence->GetCompletedValue() < value) {
        const HRESULT er = fence->SetEventOnCompletion(value, eventHandle);
        if (FAILED(er)) { RunLog("%s_SET_EVENT_FAILED=0x%08X", stage, static_cast<unsigned>(er)); return false; }
        const DWORD wr = WaitForSingleObject(eventHandle, 15000);
        if (wr != WAIT_OBJECT_0) { RunLog("%s_WAIT_RESULT=%lu", stage, wr); return false; }
    }
    const HRESULT removed = device->GetDeviceRemovedReason();
    RunLog("%s_DEVICE_REMOVED_REASON=0x%08X", stage, static_cast<unsigned>(removed));
    return SUCCEEDED(removed);
}

static bool Upload(Texture &texture, ID3D12Device *device, ID3D12CommandAllocator *allocator,
    ID3D12GraphicsCommandList *list, ID3D12CommandQueue *queue, ID3D12Fence *fence,
    HANDLE eventHandle, UINT64 &fenceValue) {
    uint8_t *mapped = texture.mappedUpload;
    if (!mapped) { RunLog("UPLOAD_MAP_FAILED name=%s", texture.name); return false; }
    for (UINT row = 0; row < texture.height; ++row) std::memcpy(mapped + static_cast<size_t>(row) * texture.footprint.Footprint.RowPitch,
        texture.packed.data() + static_cast<size_t>(row) * texture.rowBytes, texture.rowBytes);
    if (!ResetList(allocator, list, texture.name)) return false;
    D3D12_TEXTURE_COPY_LOCATION src{}, dst{}; src.pResource = texture.upload;
    src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint = texture.footprint;
    dst.pResource = texture.gpu; dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    Transition(list, texture.gpu, texture.state, D3D12_RESOURCE_STATE_COPY_DEST);
    texture.state = D3D12_RESOURCE_STATE_COPY_DEST;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    Transition(list, texture.gpu, texture.state, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    texture.state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    const HRESULT cr = list->Close(); if (FAILED(cr)) { RunLog("UPLOAD_LIST_CLOSE_FAILED name=%s hr=0x%08X", texture.name, static_cast<unsigned>(cr)); return false; }
    ID3D12CommandList *commands[] = {list}; queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle, device, texture.name)) return false;
    RunLog("UPLOAD_COMPLETE name=%s finalState=0x%X fence=%llu", texture.name, static_cast<unsigned>(texture.state), fenceValue);
    return true;
}

static bool MapTextureUpload(Texture &texture) {
    uint8_t *mapped = texture.mappedUpload;
    if (!mapped) { RunLog("UPLOAD_MAP_FAILED name=%s", texture.name); return false; }
    for (UINT row = 0; row < texture.height; ++row) std::memcpy(mapped + static_cast<size_t>(row) * texture.footprint.Footprint.RowPitch,
        texture.packed.data() + static_cast<size_t>(row) * texture.rowBytes, texture.rowBytes);
    return true;
}

static void RecordTextureUpload(Texture &texture, ID3D12GraphicsCommandList *list,
    D3D12_RESOURCE_STATES restoreState) {
    Transition(list, texture.gpu, texture.state, D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION src{}, dst{}; src.pResource = texture.upload;
    src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint = texture.footprint;
    dst.pResource = texture.gpu; dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    Transition(list, texture.gpu, D3D12_RESOURCE_STATE_COPY_DEST, restoreState); texture.state = restoreState;
}

static bool UploadPair(Texture &first, Texture &second, ID3D12Device *device, ID3D12CommandAllocator *allocator,
    ID3D12GraphicsCommandList *list, ID3D12CommandQueue *queue, ID3D12Fence *fence,
    HANDLE eventHandle, UINT64 &fenceValue) {
    if (!MapTextureUpload(first) || !MapTextureUpload(second) || !ResetList(allocator, list, "UPLOAD_PAIR")) return false;
    RecordTextureUpload(first, list, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    RecordTextureUpload(second, list, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    if (FAILED(list->Close())) return false;
    ID3D12CommandList *commands[] = {list}; queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle, device, "UPLOAD_PAIR")) return false;
    RunLog("UPLOAD_PAIR_COMPLETE first=%s second=%s fence=%llu", first.name, second.name, fenceValue);
    return true;
}
static void RecordDisableZero(Buffer &disable, ID3D12GraphicsCommandList *list) {
    Transition(list, disable.gpu, disable.state, D3D12_RESOURCE_STATE_COPY_DEST);
    list->CopyBufferRegion(disable.gpu, 0, disable.upload, 0, 4);
    Transition(list, disable.gpu, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    disable.state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
}

static uint16_t FloatToHalf(float value) {
    uint32_t bits = 0; std::memcpy(&bits, &value, 4); const uint32_t sign = (bits >> 16) & 0x8000u;
    const uint32_t exponent = (bits >> 23) & 0xffu; uint32_t mantissa = bits & 0x7fffffu;
    if (exponent == 255) return static_cast<uint16_t>(sign | 0x7c00u | (mantissa ? 0x200u : 0));
    const int adjusted = static_cast<int>(exponent) - 127 + 15;
    if (adjusted >= 31) return static_cast<uint16_t>(sign | 0x7c00u);
    if (adjusted <= 0) { if (adjusted < -10) return static_cast<uint16_t>(sign); mantissa |= 0x800000u; return static_cast<uint16_t>(sign | (mantissa >> (14 - adjusted))); }
    return static_cast<uint16_t>(sign | (static_cast<uint32_t>(adjusted) << 10) | (mantissa >> 13));
}
static void Identity(float matrix[4][4]) { std::memset(matrix, 0, sizeof(float) * 16); for (int i = 0; i < 4; ++i) matrix[i][i] = 1.0f; }
static void SetResource(NVSDK_NGX_Parameter *p, const char *key, ID3D12Resource *r) { NVSDK_NGX_Parameter_SetD3d12Resource(p, key, r); }
static bool VerifyResource(NVSDK_NGX_Parameter *p, const char *key, ID3D12Resource *expected) {
    ID3D12Resource *actual = nullptr; const NVSDK_NGX_Result result = p->Get(key, &actual);
    const bool match = NVSDK_NGX_SUCCEED(result) && actual == expected;
    RunLog("PARAM_RESOURCE key=%s result=0x%08X expected=%p actual=%p match=%d", key, result,
        static_cast<void *>(expected), static_cast<void *>(actual), match ? 1 : 0); return match;
}

static int QueryCapabilityValue(NVSDK_NGX_Parameter *parameters, const char *stage) {
    int available = 0, maximum = 0, superSampling = 0;
    unsigned int featureInit = 0;
    const NVSDK_NGX_Result availableResult = parameters
        ? parameters->Get(NVSDK_NGX_Parameter_FrameGeneration_Available, &available)
        : NVSDK_NGX_Result_FAIL_InvalidParameter;
    const NVSDK_NGX_Result maximumResult = parameters
        ? parameters->Get(NVSDK_NGX_DLSSG_Parameter_MultiFrameCountMax, &maximum)
        : NVSDK_NGX_Result_FAIL_InvalidParameter;
    const NVSDK_NGX_Result featureInitResult = parameters
        ? parameters->Get(NVSDK_NGX_Parameter_FrameGeneration_FeatureInitResult, &featureInit)
        : NVSDK_NGX_Result_FAIL_InvalidParameter;
    const NVSDK_NGX_Result superSamplingResult = parameters
        ? parameters->Get(NVSDK_NGX_Parameter_SuperSampling_Available, &superSampling)
        : NVSDK_NGX_Result_FAIL_InvalidParameter;
    RunLog("CAPABILITY_STAGE=%s", stage);
    RunLog("FRAME_GENERATION_AVAILABLE_RESULT=0x%08X VALUE=%s%d", availableResult,
        NVSDK_NGX_SUCCEED(availableResult) ? "" : "MISSING_", available);
    RunLog("MULTIFRAME_COUNT_MAX_RESULT=0x%08X VALUE=%s%d", maximumResult,
        NVSDK_NGX_SUCCEED(maximumResult) ? "" : "MISSING_", maximum);
    RunLog("FRAME_GENERATION_FEATURE_INIT_RESULT=0x%08X VALUE=%s0x%08X", featureInitResult,
        NVSDK_NGX_SUCCEED(featureInitResult) ? "" : "MISSING_", featureInit);
    RunLog("SUPERSAMPLING_AVAILABLE_RESULT=0x%08X VALUE=%s%d", superSamplingResult,
        NVSDK_NGX_SUCCEED(superSamplingResult) ? "" : "MISSING_", superSampling);
    if (!NVSDK_NGX_SUCCEED(maximumResult) || maximum < 1 || maximum > 3) return 1;
    return maximum;
}

static bool SetOptions(NVSDK_NGX_Parameter *p, ID3D12Resource *color, ID3D12Resource *depth,
    ID3D12Resource *motion, ID3D12Resource *output, ID3D12Resource *disable, bool reset,
    unsigned long long frameId, uint32_t generatedCount, uint32_t generatedIndex, NVSDK_NGX_DLSSG_Opt_Eval_Params &o, bool manifest,
    UINT width = kWidth, UINT height = kHeight) {
    o = {}; o.multiFrameCount = generatedCount; o.multiFrameIndex = generatedIndex;
    Identity(o.cameraViewToClip); Identity(o.clipToCameraView); Identity(o.clipToLensClip);
    Identity(o.clipToPrevClip); Identity(o.prevClipToClip);
    o.mvecScale[0] = 1.0f / width; o.mvecScale[1] = 1.0f / height;
    o.cameraNear = 0.1f; o.cameraFar = 1000.0f; o.cameraFOV = 1.04719755f; o.cameraAspectRatio = 1.0f;
    o.reset = reset; o.orthoProjection = true; o.motionVectorsInvalidValue = -65500.0f;
    o.motionVectorsDilated = true; o.mvecsSubrectSize = {width, height};
    o.depthSubrectSize = {width, height}; o.hudLessSubrectSize = {width, height};
    o.backbufferSubrectSize = {width, height}; o.outputInterpSubrectSize = {width, height};

    SetResource(p, NVSDK_NGX_DLSSG_Parameter_Backbuffer, color);
    SetResource(p, NVSDK_NGX_DLSSG_Parameter_MVecs, motion);
    SetResource(p, NVSDK_NGX_DLSSG_Parameter_Depth, depth);
    SetResource(p, NVSDK_NGX_DLSSG_Parameter_HUDLess, color);
    SetResource(p, NVSDK_NGX_DLSSG_Parameter_UI, nullptr);
    SetResource(p, NVSDK_NGX_DLSSG_Parameter_UIAlpha, nullptr);
    SetResource(p, NVSDK_NGX_DLSSG_Parameter_BidirectionalDistortionField, nullptr);
    SetResource(p, NVSDK_NGX_DLSSG_Parameter_OutputInterpolated, output);
    SetResource(p, NVSDK_NGX_DLSSG_Parameter_OutputReal, nullptr);
    SetResource(p, NVSDK_NGX_DLSSG_Parameter_OutputDisableInterpolation, disable);
    NVSDK_NGX_Parameter_SetUI(p, NVSDK_NGX_DLSSG_Parameter_MultiFrameCount, o.multiFrameCount);
    NVSDK_NGX_Parameter_SetUI(p, NVSDK_NGX_DLSSG_Parameter_MultiFrameIndex, o.multiFrameIndex);
    p->Set(NVSDK_NGX_DLSSG_Parameter_BackbufferFrameID, frameId);
    unsigned int storedCount = 0, storedIndex = 0;
    const NVSDK_NGX_Result countResult = p->Get(NVSDK_NGX_DLSSG_Parameter_MultiFrameCount, &storedCount);
    const NVSDK_NGX_Result indexResult = p->Get(NVSDK_NGX_DLSSG_Parameter_MultiFrameIndex, &storedIndex);
    RunLog("MFG_REQUEST frame=%llu count=%u index=%u countResult=0x%08X indexResult=0x%08X",
        frameId, storedCount, storedIndex, countResult, indexResult);

#define SET_F(key, value) NVSDK_NGX_Parameter_SetF(p, key, value)
#define SET_UI(key, value) NVSDK_NGX_Parameter_SetUI(p, key, value)
#define SET_VP(key, value) NVSDK_NGX_Parameter_SetVoidPointer(p, key, value)
    SET_VP(NVSDK_NGX_DLSSG_Parameter_CameraViewToClip, o.cameraViewToClip);
    SET_VP(NVSDK_NGX_DLSSG_Parameter_ClipToCameraView, o.clipToCameraView);
    SET_VP(NVSDK_NGX_DLSSG_Parameter_ClipToLensClip, o.clipToLensClip);
    SET_VP(NVSDK_NGX_DLSSG_Parameter_ClipToPrevClip, o.clipToPrevClip);
    SET_VP(NVSDK_NGX_DLSSG_Parameter_PrevClipToClip, o.prevClipToClip);
    SET_F(NVSDK_NGX_DLSSG_Parameter_JitterOffsetX, o.jitterOffset[0]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_JitterOffsetY, o.jitterOffset[1]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_MvecScaleX, o.mvecScale[0]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_MvecScaleY, o.mvecScale[1]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_CameraPinholeOffsetX, o.cameraPinholeOffset[0]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_CameraPinholeOffsetY, o.cameraPinholeOffset[1]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_CameraPosX, o.cameraPos[0]); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraPosY, o.cameraPos[1]); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraPosZ, o.cameraPos[2]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_CameraUpX, o.cameraUp[0]); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraUpY, o.cameraUp[1]); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraUpZ, o.cameraUp[2]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_CameraRightX, o.cameraRight[0]); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraRightY, o.cameraRight[1]); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraRightZ, o.cameraRight[2]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_CameraFwdX, o.cameraFwd[0]); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraFwdY, o.cameraFwd[1]); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraFwdZ, o.cameraFwd[2]);
    SET_F(NVSDK_NGX_DLSSG_Parameter_CameraNear, o.cameraNear); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraFar, o.cameraFar);
    SET_F(NVSDK_NGX_DLSSG_Parameter_CameraFOV, o.cameraFOV); SET_F(NVSDK_NGX_DLSSG_Parameter_CameraAspectRatio, o.cameraAspectRatio);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_ColorBuffersHDR, o.colorBuffersHDR);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_DepthInverted, o.depthInverted);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_CameraMotionIncluded, o.cameraMotionIncluded);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_Reset, o.reset);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_AutomodeOverrideReset, o.automodeOverrideReset);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_NotRenderingGameFrames, o.notRenderingGameFrames);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_OrthoProjection, o.orthoProjection);
    SET_F(NVSDK_NGX_DLSSG_Parameter_MvecInvalidValue, o.motionVectorsInvalidValue);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_MvecDilated, o.motionVectorsDilated);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_MenuDetectionEnabled, o.menuDetectionEnabled);

    const auto rect = [&](const char *bx, const char *by, const char *w, const char *h,
        const NVSDK_NGX_Coordinates &base, const NVSDK_NGX_Dimensions &size) {
        SET_UI(bx, base.X); SET_UI(by, base.Y); SET_UI(w, size.Width); SET_UI(h, size.Height);
    };
    rect(NVSDK_NGX_DLSSG_Parameter_MVecsSubrectBaseX, NVSDK_NGX_DLSSG_Parameter_MVecsSubrectBaseY,
        NVSDK_NGX_DLSSG_Parameter_MVecsSubrectWidth, NVSDK_NGX_DLSSG_Parameter_MVecsSubrectHeight, o.mvecsSubrectBase, o.mvecsSubrectSize);
    rect(NVSDK_NGX_DLSSG_Parameter_DepthSubrectBaseX, NVSDK_NGX_DLSSG_Parameter_DepthSubrectBaseY,
        NVSDK_NGX_DLSSG_Parameter_DepthSubrectWidth, NVSDK_NGX_DLSSG_Parameter_DepthSubrectHeight, o.depthSubrectBase, o.depthSubrectSize);
    rect(NVSDK_NGX_DLSSG_Parameter_HUDLessSubrectBaseX, NVSDK_NGX_DLSSG_Parameter_HUDLessSubrectBaseY,
        NVSDK_NGX_DLSSG_Parameter_HUDLessSubrectWidth, NVSDK_NGX_DLSSG_Parameter_HUDLessSubrectHeight, o.hudLessSubrectBase, o.hudLessSubrectSize);
    rect(NVSDK_NGX_DLSSG_Parameter_UISubrectBaseX, NVSDK_NGX_DLSSG_Parameter_UISubrectBaseY,
        NVSDK_NGX_DLSSG_Parameter_UISubrectWidth, NVSDK_NGX_DLSSG_Parameter_UISubrectHeight, o.uiSubrectBase, o.uiSubrectSize);
    rect(NVSDK_NGX_DLSSG_Parameter_UIAlphaSubrectBaseX, NVSDK_NGX_DLSSG_Parameter_UIAlphaSubrectBaseY,
        NVSDK_NGX_DLSSG_Parameter_UIAlphaSubrectWidth, NVSDK_NGX_DLSSG_Parameter_UIAlphaSubrectHeight, o.uiAlphaSubrectBase, o.uiAlphaSubrectSize);
    rect(NVSDK_NGX_DLSSG_Parameter_BidirectionalDistortionFieldSubrectBaseX, NVSDK_NGX_DLSSG_Parameter_BidirectionalDistortionFieldSubrectBaseY,
        NVSDK_NGX_DLSSG_Parameter_BidirectionalDistortionFieldSubrectWidth, NVSDK_NGX_DLSSG_Parameter_BidirectionalDistortionFieldSubrectHeight,
        o.bidirectionalDistFieldSubrectBase, o.bidirectionalDistFieldSubrectSize);
    SET_UI(NVSDK_NGX_DLSSG_Parameter_BidirectionalDistortionField_LowPrecision_IsLowPrecision, o.bidirectionalDistFieldPrecisionInfo.IsLowPrecision);
    SET_F(NVSDK_NGX_DLSSG_Parameter_BidirectionalDistortionField_LowPrecision_Bias, o.bidirectionalDistFieldPrecisionInfo.Bias);
    SET_F(NVSDK_NGX_DLSSG_Parameter_BidirectionalDistortionField_LowPrecision_Scale, o.bidirectionalDistFieldPrecisionInfo.Scale);
    SET_F(NVSDK_NGX_DLSSG_Parameter_MinRelativeLinearDepthObjectSeparation, o.minRelativeLinearDepthObjectSeparation);
    rect(NVSDK_NGX_DLSSG_Parameter_InputBackbufferSubrectBaseX, NVSDK_NGX_DLSSG_Parameter_InputBackbufferSubrectBaseY,
        NVSDK_NGX_DLSSG_Parameter_InputBackbufferSubrectWidth, NVSDK_NGX_DLSSG_Parameter_InputBackbufferSubrectHeight, o.backbufferSubrectBase, o.backbufferSubrectSize);
    rect(NVSDK_NGX_DLSSG_Parameter_OutputInterpolatedSubrectBaseX, NVSDK_NGX_DLSSG_Parameter_OutputInterpolatedSubrectBaseY,
        NVSDK_NGX_DLSSG_Parameter_OutputInterpolatedSubrectWidth, NVSDK_NGX_DLSSG_Parameter_OutputInterpolatedSubrectHeight, o.outputInterpSubrectBase, o.outputInterpSubrectSize);
    rect(NVSDK_NGX_DLSSG_Parameter_OutputRealSubrectBaseX, NVSDK_NGX_DLSSG_Parameter_OutputRealSubrectBaseY,
        NVSDK_NGX_DLSSG_Parameter_OutputRealSubrectWidth, NVSDK_NGX_DLSSG_Parameter_OutputRealSubrectHeight, o.outputRealSubrectBase, o.outputRealSubrectSize);
#undef SET_F
#undef SET_UI
#undef SET_VP

    bool match = true;
    match &= VerifyResource(p, NVSDK_NGX_DLSSG_Parameter_Backbuffer, color);
    match &= VerifyResource(p, NVSDK_NGX_DLSSG_Parameter_MVecs, motion);
    match &= VerifyResource(p, NVSDK_NGX_DLSSG_Parameter_Depth, depth);
    match &= VerifyResource(p, NVSDK_NGX_DLSSG_Parameter_HUDLess, color);
    match &= VerifyResource(p, NVSDK_NGX_DLSSG_Parameter_OutputInterpolated, output);
    match &= VerifyResource(p, NVSDK_NGX_DLSSG_Parameter_OutputDisableInterpolation, disable);
    if (manifest) {
        RunLog("BOOTSTRAP_MANIFEST_BEGIN");
        RunLog("CREATE generic=%ux%u dlssg=%ux%u format=%u internal=%ux%u dynamic=0", width, height,
            width, height, static_cast<unsigned>(DXGI_FORMAT_R8G8B8A8_UNORM), width, height);
        RunLog("EVAL FrameID=%llu type=ULL Reset=%u MultiFrameCount=1 MultiFrameIndex=1", frameId, reset ? 1u : 0u);
        RunLog("EVAL matrices=%p,%p,%p,%p,%p lifetime=CALLER_OWNED", static_cast<void *>(o.cameraViewToClip),
            static_cast<void *>(o.clipToCameraView), static_cast<void *>(o.clipToLensClip),
            static_cast<void *>(o.clipToPrevClip), static_cast<void *>(o.prevClipToClip));
        RunLog("EVAL jitter=0,0 mvecScale=%.9f,%.9f pinhole=0,0 near=%.3f far=%.3f fov=%.8f aspect=%.3f",
            o.mvecScale[0], o.mvecScale[1], o.cameraNear, o.cameraFar, o.cameraFOV, o.cameraAspectRatio);
        RunLog("EVAL HDR=0 DepthInverted=0 CameraMotionIncluded=0 AutoReset=0 NotRendering=0 Ortho=1 InvalidMV=%.1f Dilated=1 Menu=0", o.motionVectorsInvalidValue);
        RunLog("EVAL nonnullRects=mvec,depth,hudless,backbuffer,outputInterp base=0,0 size=%ux%u nullRects=0,0/0x0", width, height);
        RunLog("BOOTSTRAP_MANIFEST_END"); RunLog("KNOWN_WORKER_CONTRACT_MATCH=%d", match ? 1 : 0);
    }
    return match;
}

static bool VerifyNvapi(const DXGI_ADAPTER_DESC1 &desc) {
    HMODULE nvapi = LoadLibraryExW(L"nvapi64.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!nvapi) { RunLog("NVAPI_LOAD_FAILED winerr=%lu", GetLastError()); return false; }
    auto query = reinterpret_cast<QueryFn>(GetProcAddress(nvapi, "nvapi_QueryInterface"));
    auto init = query ? reinterpret_cast<NvInitFn>(query(0x0150E828)) : nullptr;
    auto enumerate = query ? reinterpret_cast<NvEnumFn>(query(0xE5AC921F)) : nullptr;
    auto adapterId = query ? reinterpret_cast<NvAdapterIdFn>(query(0x0FF07FDE)) : nullptr;
    auto getArch = query ? reinterpret_cast<NvArchFn>(query(0xD8265D24)) : nullptr;
    NvPhysicalGpuHandle gpus[NVAPI_MAX_PHYSICAL_GPUS]{}; NvU32 count = 0; NvPhysicalGpuHandle matched = nullptr; unsigned matches = 0;
    if (!init || init() != NVAPI_OK || !enumerate || enumerate(gpus, &count) != NVAPI_OK || !adapterId || !getArch) {
        RunLog("NVAPI_INITIALIZATION_FAILED"); FreeLibrary(nvapi); return false;
    }
    for (NvU32 i = 0; i < count; ++i) { LUID luid{}; if (adapterId(gpus[i], &luid) == NVAPI_OK &&
        luid.LowPart == desc.AdapterLuid.LowPart && luid.HighPart == desc.AdapterLuid.HighPart) { matched = gpus[i]; ++matches; } }
    NV_GPU_ARCH_INFO info{}; info.version = NV_GPU_ARCH_INFO_VER;
    const bool ok = matches == 1 && getArch(matched, &info) == NVAPI_OK && info.architecture == 0x170;
    RunLog("NVAPI_FULL_LUID_MATCH=%d", matches == 1 ? 1 : 0); RunLog("NVAPI_NATIVE_ARCH=0x%X", info.architecture);
    RunLog("NVAPI_IMPLEMENTATION=0x%X", info.implementation); FreeLibrary(nvapi); return ok;
}

static bool Readback(Texture &output, Buffer &disable, ID3D12Device *device,
    ID3D12CommandAllocator *allocator, ID3D12GraphicsCommandList *list, ID3D12CommandQueue *queue,
    ID3D12Fence *fence, HANDLE eventHandle, UINT64 &fenceValue, std::vector<uint8_t> &packed,
    uint32_t &disableValue) {
    if (!ResetList(allocator, list, "OUTPUT_READBACK")) return false;
    Transition(list, output.gpu, output.state, D3D12_RESOURCE_STATE_COPY_SOURCE); output.state = D3D12_RESOURCE_STATE_COPY_SOURCE;
    Transition(list, disable.gpu, disable.state, D3D12_RESOURCE_STATE_COPY_SOURCE); disable.state = D3D12_RESOURCE_STATE_COPY_SOURCE;
    D3D12_TEXTURE_COPY_LOCATION src{}, dst{}; src.pResource = output.gpu; src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    dst.pResource = output.readback; dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint = output.footprint;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr); list->CopyBufferRegion(disable.readback, 0, disable.gpu, 0, 4);
    Transition(list, output.gpu, output.state, D3D12_RESOURCE_STATE_UNORDERED_ACCESS); output.state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    Transition(list, disable.gpu, disable.state, D3D12_RESOURCE_STATE_UNORDERED_ACCESS); disable.state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    if (FAILED(list->Close())) return false; ID3D12CommandList *commands[] = {list}; queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle, device, "OUTPUT_READBACK")) return false;
    uint8_t *mapped = nullptr; D3D12_RANGE range{0, static_cast<SIZE_T>(output.allocationBytes)};
    if (FAILED(output.readback->Map(0, &range, reinterpret_cast<void **>(&mapped)))) return false;
    packed.resize(static_cast<size_t>(output.rowBytes) * output.height);
    for (UINT row = 0; row < output.height; ++row) std::memcpy(packed.data() + static_cast<size_t>(row) * output.rowBytes,
        mapped + static_cast<size_t>(row) * output.footprint.Footprint.RowPitch, output.rowBytes);
    output.readback->Unmap(0, nullptr); uint8_t *disableMapped = nullptr; D3D12_RANGE disableRange{0, 4};
    if (FAILED(disable.readback->Map(0, &disableRange, reinterpret_cast<void **>(&disableMapped)))) return false;
    std::memcpy(&disableValue, disableMapped, 4); disable.readback->Unmap(0, nullptr); return true;
}

static double Mad(const std::vector<uint8_t> &a, const std::vector<uint8_t> &b) {
    if (a.size() != b.size() || a.empty()) return -1.0; long double total = 0;
    for (size_t i = 0; i < a.size(); ++i) total += std::abs(static_cast<int>(a[i]) - static_cast<int>(b[i]));
    return static_cast<double>(total / static_cast<long double>(a.size()));
}
static fs::path OutputDirectory() {
    wchar_t path[32768]{}; const DWORD length = GetModuleFileNameW(nullptr, path, static_cast<DWORD>(std::size(path)));
    if (!length || length == std::size(path)) return fs::path(L"runtime") / L"output";
    return fs::path(path).parent_path().parent_path() / L"runtime" / L"output";
}

int Run2x(const wchar_t *communityPath, const wchar_t *runtimeDir) {
    RunLog("PROCESS_ENTRY"); RunLog("ARGS_PARSED"); RunLog("SWAPCHAIN_USED=0"); RunLog("PRESENT_USED=0");
    RunLog("PARAM_OBJECT_PROVENANCE=OFFICIAL_NVIDIA_NGX"); RunLog("FEATURE_HANDLE_PROVENANCE=COMMUNITY_SM86_RUNTIME");
    RunLog("EVALUATE_IMPLEMENTATION=COMMUNITY_SM86_RUNTIME");
    IDXGIFactory6 *factory = nullptr; IDXGIAdapter1 *adapter = nullptr; DXGI_ADAPTER_DESC1 desc{};
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)))) return 30;
    for (UINT i = 0; factory->EnumAdapters1(i, &adapter) != DXGI_ERROR_NOT_FOUND; ++i) { DXGI_ADAPTER_DESC1 candidate{}; adapter->GetDesc1(&candidate);
        if (!(candidate.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) && candidate.VendorId == 0x10DE) { desc = candidate; break; } RunRelease(adapter); }
    if (!adapter) return 31; char adapterName[128]{}; WideCharToMultiByte(CP_UTF8, 0, desc.Description, -1, adapterName, static_cast<int>(std::size(adapterName)), nullptr, nullptr);
    RunLog("GPU_IDENTIFIED=%s vendor=0x%04X luid=%08X:%08X", adapterName, desc.VendorId, desc.AdapterLuid.HighPart, desc.AdapterLuid.LowPart);
    if (!VerifyNvapi(desc)) return 32;

    ID3D12Device *device = nullptr; ID3D12CommandQueue *queue = nullptr; ID3D12CommandAllocator *allocator = nullptr;
    ID3D12GraphicsCommandList *list = nullptr; ID3D12Fence *fence = nullptr; D3D12_COMMAND_QUEUE_DESC queueDesc{}; queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    if (FAILED(D3D12CreateDevice(adapter, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device))) ||
        FAILED(device->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&queue))) ||
        FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator))) ||
        FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator, nullptr, IID_PPV_ARGS(&list))) ||
        FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)))) return 33;
    RunLog("D3D12_CREATED=1"); RunLog("QUEUE_CREATED=1"); const HRESULT initialClose = list->Close();
    RunLog("INITIAL_COMMAND_LIST_CLOSE_RESULT=0x%08X", static_cast<unsigned>(initialClose)); if (FAILED(initialClose)) return 34;
    HANDLE eventHandle = CreateEventW(nullptr, FALSE, FALSE, nullptr); if (!eventHandle) return 35; UINT64 fenceValue = 0;

    const wchar_t *paths[] = {runtimeDir}; NVSDK_NGX_FeatureCommonInfo common{}; common.PathListInfo.Path = paths; common.PathListInfo.Length = 1;
    const char *projectId = "f8a17d65-4f1e-4e82-b0f2-4f6f93a7c8c1"; RunLog("NGX_INIT_STARTED");
    const NVSDK_NGX_Result officialInit = NVSDK_NGX_D3D12_Init_with_ProjectID(projectId, NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0", runtimeDir, device, &common, NVSDK_NGX_Version_API);
    RunLog("NGX_INIT_RESULT=0x%08X", officialInit); if (NVSDK_NGX_FAILED(officialInit)) return 36;
    NVSDK_NGX_Parameter *parameters = nullptr; const NVSDK_NGX_Result parameterResult = NVSDK_NGX_D3D12_GetCapabilityParameters(&parameters);
    RunLog("OFFICIAL_PARAMETER_ALLOCATION_RESULT=0x%08X ptr=%p", parameterResult, static_cast<void *>(parameters));
    if (NVSDK_NGX_FAILED(parameterResult) || !parameters) return 37;
    HMODULE community = LoadLibraryW(communityPath); if (!community) { RunLog("COMMUNITY_LOAD_FAILED winerr=%lu", GetLastError()); return 38; }
    auto init = reinterpret_cast<InitFn>(GetProcAddress(community, "NVSDK_NGX_D3D12_Init"));
    auto create = reinterpret_cast<CreateFn>(GetProcAddress(community, "NVSDK_NGX_D3D12_CreateFeature"));
    auto evaluate = reinterpret_cast<EvalFn>(GetProcAddress(community, "NVSDK_NGX_D3D12_EvaluateFeature"));
    RunLog("COMMUNITY_MODULE=%p", static_cast<void *>(community)); RunLog("EVALUATE_EXPORT_ADDRESS=%p", reinterpret_cast<void *>(evaluate));
    if (!init || !create || !evaluate) return 39; const NVSDK_NGX_Result communityInit = init(projectId, NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0", runtimeDir, device, &common, NVSDK_NGX_Version_API);
    RunLog("COMMUNITY_INIT_RESULT=0x%08X", communityInit); if (NVSDK_NGX_FAILED(communityInit)) return 40;

    Texture colorA{}, colorB{}, depthA{}, depthB{}, motionA{}, motionB{}, output{};
    if (!MakeTexture(device, colorA, "COLOR_A", DXGI_FORMAT_R8G8B8A8_UNORM, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST) ||
        !MakeTexture(device, colorB, "COLOR_B", DXGI_FORMAT_R8G8B8A8_UNORM, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST) ||
        !MakeTexture(device, depthA, "DEPTH_A", DXGI_FORMAT_R32_FLOAT, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST) ||
        !MakeTexture(device, depthB, "DEPTH_B", DXGI_FORMAT_R32_FLOAT, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST) ||
        !MakeTexture(device, motionA, "MV_A", DXGI_FORMAT_R16G16_FLOAT, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST) ||
        !MakeTexture(device, motionB, "MV_B", DXGI_FORMAT_R16G16_FLOAT, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST) ||
        !MakeTexture(device, output, "OUTPUT_INTERPOLATED", DXGI_FORMAT_R8G8B8A8_UNORM, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_UNORDERED_ACCESS)) return 41;
    Buffer disable{}; disable.gpu = MakeBuffer(device, 4, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    disable.upload = MakeBuffer(device, 4, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_GENERIC_READ);
    disable.readback = MakeBuffer(device, 4, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST);
    disable.state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS; if (!disable.gpu || !disable.upload || !disable.readback) return 42;
    uint8_t *disableUpload = nullptr; if (FAILED(disable.upload->Map(0, nullptr, reinterpret_cast<void **>(&disableUpload)))) return 43;
    std::memset(disableUpload, 0, 4); disable.upload->Unmap(0, nullptr);

    const uint8_t background[] = {16, 24, 32, 255}, square[] = {240, 220, 64, 255}; const float depthValue = 0.5f;
    const uint16_t motionX = FloatToHalf(-8.0f);
    for (UINT y = 0; y < kHeight; ++y) for (UINT x = 0; x < kWidth; ++x) { const size_t offset = (static_cast<size_t>(y) * kWidth + x) * 4;
        const bool a = x >= 64 && x < 128 && y >= 96 && y < 160, b = x >= 72 && x < 136 && y >= 96 && y < 160;
        std::memcpy(colorA.packed.data() + offset, a ? square : background, 4); std::memcpy(colorB.packed.data() + offset, b ? square : background, 4);
        std::memcpy(depthA.packed.data() + offset, &depthValue, 4); std::memcpy(depthB.packed.data() + offset, &depthValue, 4);
        if (b) std::memcpy(motionB.packed.data() + offset, &motionX, sizeof(motionX)); }
    for (size_t i = 0; i < output.packed.size(); i += 4) { output.packed[i] = 3; output.packed[i + 1] = 5; output.packed[i + 2] = 7; output.packed[i + 3] = 255; }
    uint8_t *outputUpload = nullptr; if (FAILED(output.upload->Map(0, nullptr, reinterpret_cast<void **>(&outputUpload)))) return 44;
    for (UINT row = 0; row < kHeight; ++row) std::memcpy(outputUpload + static_cast<size_t>(row) * output.footprint.Footprint.RowPitch,
        output.packed.data() + static_cast<size_t>(row) * kRowBytes, kRowBytes); output.upload->Unmap(0, nullptr);
    std::vector<Texture *> inputs = {&colorA, &colorB, &depthA, &depthB, &motionA, &motionB};
    for (Texture *input : inputs) if (!Upload(*input, device, allocator, list, queue, fence, eventHandle, fenceValue)) { RunLog("UPLOAD_REGRESSION resource=%s state=0x%X", input->name, static_cast<unsigned>(input->state)); return 45; }
    RunLog("INPUT_FINAL_STATES colorA=0x%X colorB=0x%X depthA=0x%X depthB=0x%X mvA=0x%X mvB=0x%X",
        static_cast<unsigned>(colorA.state), static_cast<unsigned>(colorB.state), static_cast<unsigned>(depthA.state),
        static_cast<unsigned>(depthB.state), static_cast<unsigned>(motionA.state), static_cast<unsigned>(motionB.state));
    RunLog("OUTPUT_FINAL_STATE=0x%X OUTPUT_DISABLE_FINAL_STATE=0x%X", static_cast<unsigned>(output.state), static_cast<unsigned>(disable.state));

    const unsigned alwaysFlags = NVSDK_NGX_DLSSG_ResourceFlags_Backbuffer | NVSDK_NGX_DLSSG_ResourceFlags_MVecs |
        NVSDK_NGX_DLSSG_ResourceFlags_Depth | NVSDK_NGX_DLSSG_ResourceFlags_HUDLess |
        NVSDK_NGX_DLSSG_ResourceFlags_OutputInterpolated | NVSDK_NGX_DLSSG_ResourceFlags_OutputDisableInterpolation;
    const unsigned neverFlags = NVSDK_NGX_DLSSG_ResourceFlags_UI | NVSDK_NGX_DLSSG_ResourceFlags_UIAlpha |
        NVSDK_NGX_DLSSG_ResourceFlags_BidirectionalDistortionField | NVSDK_NGX_DLSSG_ResourceFlags_OutputReal;
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_CreationNodeMask, 1);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_VisibilityNodeMask, 1);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_Width, kWidth);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_Parameter_Height, kHeight);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_DLSSG_Parameter_Width, kWidth);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_DLSSG_Parameter_Height, kHeight);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_DLSSG_Parameter_BackbufferFormat, static_cast<unsigned>(DXGI_FORMAT_R8G8B8A8_UNORM));
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_DLSSG_Parameter_InternalWidth, kWidth);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_DLSSG_Parameter_InternalHeight, kHeight);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_DLSSG_Parameter_DynamicResolution, 0);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_DLSSG_Parameter_ResourceAlwaysProvided_Flags, alwaysFlags);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_DLSSG_Parameter_ResourceNeverProvided_Flags, neverFlags);
    NVSDK_NGX_Parameter_SetUI(parameters, NVSDK_NGX_DLSSG_Parameter_UserInterfaceRecompositionEnabled, 0);
    unsigned verifyWidth = 0, verifyHeight = 0, verifyAlways = 0, verifyNever = 0;
    parameters->Get(NVSDK_NGX_DLSSG_Parameter_Width, &verifyWidth); parameters->Get(NVSDK_NGX_DLSSG_Parameter_Height, &verifyHeight);
    parameters->Get(NVSDK_NGX_DLSSG_Parameter_ResourceAlwaysProvided_Flags, &verifyAlways);
    parameters->Get(NVSDK_NGX_DLSSG_Parameter_ResourceNeverProvided_Flags, &verifyNever);
    RunLog("CREATE_FLAGS always=0x%08X never=0x%08X uiRecomposition=0", verifyAlways, verifyNever);
    if (verifyWidth != kWidth || verifyHeight != kHeight || verifyAlways != alwaysFlags || verifyNever != neverFlags) return 46;

    if (!ResetList(allocator, list, "CREATE")) return 47; NVSDK_NGX_Handle *feature = nullptr;
    RunLog("COMMUNITY_CREATE_STARTED"); const NVSDK_NGX_Result createResult = create(list, NVSDK_NGX_Feature_FrameGeneration, parameters, &feature);
    RunLog("COMMUNITY_CREATE_RESULT=0x%08X handle=%p", createResult, static_cast<void *>(feature));
    if (NVSDK_NGX_FAILED(createResult) || !feature) return 48; if (FAILED(list->Close())) return 49;
    ID3D12CommandList *commands[] = {list}; queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle, device, "CREATE")) return 50;

    NVSDK_NGX_DLSSG_Opt_Eval_Params bootstrapOptions{}; if (!ResetList(allocator, list, "BOOTSTRAP")) return 51;
    RecordDisableZero(disable, list);
    if (!SetOptions(parameters, colorA.gpu, depthA.gpu, motionA.gpu, output.gpu, disable.gpu, true, 0ULL, 1, 1, bootstrapOptions, true)) return 52;
    RunLog("BOOTSTRAP_EVALUATE_STARTED"); const NVSDK_NGX_Result bootstrapResult = evaluate(list, feature, parameters, nullptr);
    RunLog("BOOTSTRAP_EVALUATE_RESULT=0x%08X", bootstrapResult); if (NVSDK_NGX_FAILED(bootstrapResult)) return 53;
    if (FAILED(list->Close())) return 54; queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle, device, "BOOTSTRAP")) return 55; RunLog("BOOTSTRAP_FENCE_COMPLETE=1");

    NVSDK_NGX_DLSSG_Opt_Eval_Params measuredOptions{}; if (!ResetList(allocator, list, "MEASURED")) return 56;
    RecordDisableZero(disable, list); RecordTextureUpload(output, list, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    RunLog("OUTPUT_SENTINEL_PREFILLED sha256=%s", kSentinelSha);
    if (!SetOptions(parameters, colorB.gpu, depthB.gpu, motionB.gpu, output.gpu, disable.gpu, false, 1ULL, 1, 1, measuredOptions, false)) return 57;
    RunLog("MEASURED_EVALUATE_STARTED"); const NVSDK_NGX_Result measuredResult = evaluate(list, feature, parameters, nullptr);
    RunLog("MEASURED_EVALUATE_RESULT=0x%08X", measuredResult); if (NVSDK_NGX_FAILED(measuredResult)) return 58;
    if (FAILED(list->Close())) return 59; queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle, device, "MEASURED")) return 60; RunLog("MEASURED_FENCE_COMPLETE=1");

    std::vector<uint8_t> generated; uint32_t disableValue = std::numeric_limits<uint32_t>::max();
    if (!Readback(output, disable, device, allocator, list, queue, fence, eventHandle, fenceValue, generated, disableValue)) return 61;
    const std::string generatedSha = Sha256(generated), inputASha = Sha256(colorA.packed), inputBSha = Sha256(colorB.packed);
    const bool identicalSentinel = generated == output.packed, identicalA = generated == colorA.packed, identicalB = generated == colorB.packed;
    const bool allZero = std::all_of(generated.begin(), generated.end(), [](uint8_t v) { return v == 0; });
    const bool constant = !generated.empty() && std::all_of(generated.begin(), generated.end(), [&](uint8_t v) { return v == generated.front(); });
    const uint8_t minimum = *std::min_element(generated.begin(), generated.end()), maximum = *std::max_element(generated.begin(), generated.end());
    long double sum = 0; for (uint8_t v : generated) sum += v; const double mean = static_cast<double>(sum / generated.size());
    const double madA = Mad(generated, colorA.packed), madB = Mad(generated, colorB.packed), madAB = Mad(colorA.packed, colorB.packed);
    RunLog("OUTPUT_DISABLE=%u", disableValue); RunLog("OUTPUT_ROW_PITCH=%u", output.footprint.Footprint.RowPitch);
    RunLog("OUTPUT_PACKED_SIZE=%zu", generated.size()); RunLog("OUTPUT_SHA256=%s", generatedSha.c_str());
    RunLog("IDENTICAL_TO_SENTINEL=%d", identicalSentinel ? 1 : 0); RunLog("OUTPUT_ALL_ZERO=%d", allZero ? 1 : 0);
    RunLog("OUTPUT_CONSTANT=%d", constant ? 1 : 0); RunLog("OUTPUT_MIN=%u", static_cast<unsigned>(minimum));
    RunLog("OUTPUT_MAX=%u", static_cast<unsigned>(maximum)); RunLog("OUTPUT_MEAN=%.6f", mean);
    RunLog("IDENTICAL_TO_A=%d", identicalA ? 1 : 0); RunLog("IDENTICAL_TO_B=%d", identicalB ? 1 : 0);
    RunLog("MAD_GENERATED_TO_A=%.6f", madA); RunLog("MAD_GENERATED_TO_B=%.6f", madB); RunLog("MAD_A_TO_B=%.6f", madAB);

    const fs::path outputDirectory = OutputDirectory(); std::error_code directoryError; fs::create_directories(outputDirectory, directoryError);
    if (directoryError) return 62; const fs::path rawPath = outputDirectory / L"generated_2x.raw";
    const fs::path jsonPath = outputDirectory / L"generated_2x.json"; std::ofstream raw(rawPath, std::ios::binary);
    raw.write(reinterpret_cast<const char *>(generated.data()), static_cast<std::streamsize>(generated.size())); raw.close(); if (!raw) return 63;
    std::ofstream json(jsonPath); json << "{\n  \"width\": 256,\n  \"height\": 256,\n"
        << "  \"format\": \"DXGI_FORMAT_R8G8B8A8_UNORM\",\n  \"rowPitch\": " << output.footprint.Footprint.RowPitch
        << ",\n  \"packedSize\": " << generated.size() << ",\n  \"generatedSha256\": \"" << generatedSha
        << "\",\n  \"sentinelSha256\": \"" << kSentinelSha << "\",\n  \"inputASha256\": \"" << inputASha
        << "\",\n  \"inputBSha256\": \"" << inputBSha << "\",\n  \"disableFlag\": " << disableValue
        << ",\n  \"identicalToSentinel\": " << (identicalSentinel ? "true" : "false")
        << ",\n  \"identicalToA\": " << (identicalA ? "true" : "false") << ",\n  \"identicalToB\": " << (identicalB ? "true" : "false")
        << ",\n  \"allZero\": " << (allZero ? "true" : "false") << ",\n  \"constant\": " << (constant ? "true" : "false")
        << ",\n  \"minimum\": " << static_cast<unsigned>(minimum) << ",\n  \"maximum\": " << static_cast<unsigned>(maximum)
        << ",\n  \"mean\": " << mean << ",\n  \"madGeneratedToA\": " << madA << ",\n  \"madGeneratedToB\": " << madB
        << ",\n  \"madAToB\": " << madAB << "\n}\n"; json.close(); if (!json) return 64;
    RunLog("OUTPUT_RAW_PATH=%ls", rawPath.c_str()); RunLog("OUTPUT_JSON_PATH=%ls", jsonPath.c_str()); RunLog("OUTPUT_PERSISTED=1");
    RunLog("NGX_SHUTDOWN_SKIPPED_KNOWN_HANG=1"); const bool success = disableValue == 0 && !identicalSentinel && !allZero && !constant;
    RunLog("OFFLINE_PUBLIC_NGX_ABI_2X_WORKING=%d", success ? 1 : 0); std::fflush(stderr); ExitProcess(success ? 0 : 65); return 65;
}

namespace {
using Clock = std::chrono::steady_clock;
using dlssg::protocol::Command;
using dlssg::protocol::Status;

static double Milliseconds(Clock::time_point begin, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - begin).count();
}

struct HistoryState {
    bool valid = false;
    bool hasFrameId = false;
    uint64_t lastFrameId = 0;

    bool Begin(uint64_t frameId, bool requestedReset, bool &effectiveReset) {
        if (hasFrameId && frameId <= lastFrameId) return false;
        effectiveReset = requestedReset || !valid;
        return true;
    }
    void Complete(uint64_t frameId) { lastFrameId = frameId; hasFrameId = true; valid = true; }
    void Reset() { valid = false; }
};

class PersistentWorker {
public:
    bool Initialize(const wchar_t *communityPath, const wchar_t *runtimeDir) {
        wchar_t diagnostic[8]{};
        diagnosticMode_ = GetEnvironmentVariableW(L"DLSSG_WORKER_DIAGNOSTIC", diagnostic, static_cast<DWORD>(std::size(diagnostic))) != 0;
        RunLog("WORKER_MODE=%s", diagnosticMode_ ? "DIAGNOSTIC" : "PRODUCTION");
        runtimeDir_ = runtimeDir;
        IDXGIAdapter1 *candidate = nullptr;
        if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory_)))) return false;
        for (UINT index = 0; factory_->EnumAdapters1(index, &candidate) != DXGI_ERROR_NOT_FOUND; ++index) {
            DXGI_ADAPTER_DESC1 current{}; candidate->GetDesc1(&current);
            if (!(current.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) && current.VendorId == 0x10DE) {
                adapter_ = candidate; adapterDesc_ = current; break;
            }
            RunRelease(candidate);
        }
        if (!adapter_ || !VerifyNvapi(adapterDesc_)) return false;
        char name[128]{}; WideCharToMultiByte(CP_UTF8, 0, adapterDesc_.Description, -1, name,
            static_cast<int>(std::size(name)), nullptr, nullptr);
        RunLog("WORKER_GPU=%s", name);
        D3D12_COMMAND_QUEUE_DESC queueDesc{}; queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (FAILED(D3D12CreateDevice(adapter_, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device_))) ||
            FAILED(device_->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&queue_))) ||
            FAILED(device_->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator_))) ||
            FAILED(device_->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator_, nullptr, IID_PPV_ARGS(&list_))) ||
            FAILED(device_->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence_)))) return false;
        if (FAILED(list_->Close())) return false;
        event_ = CreateEventW(nullptr, FALSE, FALSE, nullptr); if (!event_) return false;
        runtimePaths_[0] = runtimeDir_.c_str(); common_.PathListInfo.Path = runtimePaths_; common_.PathListInfo.Length = 1;
        const NVSDK_NGX_Result official = NVSDK_NGX_D3D12_Init_with_ProjectID(projectId_,
            NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0", runtimeDir, device_, &common_, NVSDK_NGX_Version_API);
        RunLog("WORKER_OFFICIAL_INIT_RESULT=0x%08X", official); if (NVSDK_NGX_FAILED(official)) return false;
        const NVSDK_NGX_Result allocated = NVSDK_NGX_D3D12_GetCapabilityParameters(&parameters_);
        RunLog("CAPABILITY_PARAMETERS_OFFICIAL_GET_RESULT=0x%08X ptr=%p", allocated, static_cast<void *>(parameters_));
        if (NVSDK_NGX_FAILED(allocated) || !parameters_) return false;
        QueryCapabilityValue(parameters_, "OFFICIAL_GET");
        community_ = LoadLibraryW(communityPath); if (!community_) return false;
        init_ = reinterpret_cast<InitFn>(GetProcAddress(community_, "NVSDK_NGX_D3D12_Init"));
        create_ = reinterpret_cast<CreateFn>(GetProcAddress(community_, "NVSDK_NGX_D3D12_CreateFeature"));
        evaluate_ = reinterpret_cast<EvalFn>(GetProcAddress(community_, "NVSDK_NGX_D3D12_EvaluateFeature"));
        releaseFeature_ = reinterpret_cast<ReleaseFeatureFn>(GetProcAddress(community_, "NVSDK_NGX_D3D12_ReleaseFeature"));
        populateParameters_ = reinterpret_cast<PopulateParametersFn>(GetProcAddress(community_, "NVSDK_NGX_D3D12_PopulateParameters_Impl"));
        populateDeviceParameters_ = reinterpret_cast<PopulateDeviceParametersFn>(GetProcAddress(community_, "NVSDK_NGX_D3D12_PopulateDeviceParameters_Impl"));
        RunLog("COMMUNITY_POPULATE_PARAMETERS_EXPORT=%p", reinterpret_cast<void *>(populateParameters_));
        RunLog("COMMUNITY_POPULATE_DEVICE_PARAMETERS_EXPORT=%p", reinterpret_cast<void *>(populateDeviceParameters_));
        QueryCapabilityValue(parameters_, "AFTER_COMMUNITY_LOAD_BEFORE_INIT");
        if (!init_ || !create_ || !evaluate_ || !releaseFeature_ || !populateParameters_ || !populateDeviceParameters_) return false;
        const NVSDK_NGX_Result communityResult = init_(projectId_, NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0",
            runtimeDir, device_, &common_, NVSDK_NGX_Version_API);
        RunLog("WORKER_COMMUNITY_INIT_RESULT=0x%08X", communityResult);
        if (NVSDK_NGX_FAILED(communityResult)) return false;
        QueryCapabilityValue(parameters_, "AFTER_COMMUNITY_INIT");
        const NVSDK_NGX_Result devicePopulate = populateDeviceParameters_(device_, parameters_);
        RunLog("COMMUNITY_POPULATE_DEVICE_PARAMETERS_RESULT=0x%08X", devicePopulate);
        QueryCapabilityValue(parameters_, "AFTER_COMMUNITY_POPULATE_DEVICE_PARAMETERS");
        const NVSDK_NGX_Result parameterPopulate = populateParameters_(parameters_);
        RunLog("COMMUNITY_POPULATE_PARAMETERS_RESULT=0x%08X", parameterPopulate);
        capabilityMax_ = QueryCapabilityValue(parameters_, "AFTER_COMMUNITY_POPULATE_PARAMETERS");
        RunLog("MULTIFRAME_MAX_SOURCE=COMMUNITY_POPULATE FINAL_GENERATED_COUNT_MAX=%d", capabilityMax_);
        int available = 0;
        const NVSDK_NGX_Result availableResult = parameters_->Get(NVSDK_NGX_Parameter_FrameGeneration_Available, &available);
        if (NVSDK_NGX_SUCCEED(availableResult) && available == 0 && capabilityMax_ >= 1 &&
            NVSDK_NGX_SUCCEED(devicePopulate) && NVSDK_NGX_SUCCEED(parameterPopulate)) {
            parameters_->Set(NVSDK_NGX_Parameter_FrameGeneration_Available, 1);
            int stored = 0;
            const NVSDK_NGX_Result verifyAvailable = parameters_->Get(NVSDK_NGX_Parameter_FrameGeneration_Available, &stored);
            RunLog("FRAME_GENERATION_AVAILABLE_SOURCE=DIRECT_HOST_ENABLE SET_RESULT=VOID VERIFY_RESULT=0x%08X VALUE=%d",
                verifyAvailable, stored);
        }
        QueryCapabilityValue(parameters_, "AFTER_DIRECT_HOST_AVAILABILITY_ENABLE");
        ++initCount_; RunLog("WORKER_INIT_COMPLETE initCount=%u", initCount_); return true;
    }

    Status Create(const dlssg::protocol::CreateRequest &request,
        dlssg::protocol::CreateResponse &response) {
        response = {dlssg::protocol::kWorkerVersion, dlssg::protocol::kVersion, static_cast<uint32_t>(capabilityMax_),
            static_cast<uint32_t>(dlssg::protocol::DepthMode::ConstantPointFive)};
        if (!request.width || !request.height || request.width > 3840 || request.height > 2160) return Status::InvalidDimensions;
        if (request.pixelFormat != static_cast<uint32_t>(DXGI_FORMAT_R8G8B8A8_UNORM)) return Status::InvalidFormat;
        if (request.generatedCount < 1 || request.generatedCount > 3 || request.generatedCount > static_cast<uint32_t>(capabilityMax_) || request.depthMode !=
            static_cast<uint32_t>(dlssg::protocol::DepthMode::ConstantPointFive) ||
            (request.motionMode != static_cast<uint32_t>(dlssg::protocol::MotionMode::ExternalR16G16Float) &&
             request.motionMode != static_cast<uint32_t>(dlssg::protocol::MotionMode::NvidiaOpticalFlow))) return Status::InvalidMessage;
        if (created_ && request.width == width_ && request.height == height_ && request.motionMode == motionMode_ && request.generatedCount == generatedPerGroup_) {
            history_.Reset(); previousColor_.clear(); nvofHistoryValid_ = false;
            RunLog("WORKER_CREATE_REUSED historyInvalid=1"); return Status::Ok;
        }
        if (created_ && !DestroyFeatureAndResources()) return Status::NativeFailure;
        width_ = request.width; height_ = request.height; motionMode_ = request.motionMode; generatedPerGroup_ = request.generatedCount;
        const UINT colorRowBytes = width_ * 4;
        if (!MakeTexture(device_, color_, "WORKER_COLOR", DXGI_FORMAT_R8G8B8A8_UNORM, D3D12_RESOURCE_FLAG_NONE,
                D3D12_RESOURCE_STATE_COPY_DEST, width_, height_, colorRowBytes) ||
            !MakeTexture(device_, depth_, "WORKER_DEPTH", DXGI_FORMAT_R32_FLOAT, D3D12_RESOURCE_FLAG_NONE,
                D3D12_RESOURCE_STATE_COPY_DEST, width_, height_, width_ * 4) ||
            !MakeTexture(device_, motion_, "WORKER_MOTION", DXGI_FORMAT_R16G16_FLOAT, D3D12_RESOURCE_FLAG_NONE,
                D3D12_RESOURCE_STATE_COPY_DEST, width_, height_, width_ * 4) ||
            !MakeTexture(device_, output_, "WORKER_OUTPUT", DXGI_FORMAT_R8G8B8A8_UNORM,
                D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                width_, height_, colorRowBytes)) return Status::NativeFailure;
        disable_.gpu = MakeBuffer(device_, 4, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        disable_.upload = MakeBuffer(device_, 4, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_GENERIC_READ);
        disable_.readback = MakeBuffer(device_, 4, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST);
        disable_.state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
        if (!disable_.gpu || !disable_.upload || !disable_.readback) return Status::NativeFailure;
        uint8_t *mapped = nullptr; if (FAILED(disable_.upload->Map(0, nullptr, reinterpret_cast<void **>(&mapped)))) return Status::NativeFailure;
        std::memset(mapped, 0, 4); disable_.upload->Unmap(0, nullptr);
        const float depthValue = 0.5f;
        for (size_t offset = 0; offset < depth_.packed.size(); offset += 4) std::memcpy(depth_.packed.data() + offset, &depthValue, 4);
        for (size_t offset = 0; offset < output_.packed.size(); offset += 4) {
            output_.packed[offset] = 3; output_.packed[offset + 1] = 5; output_.packed[offset + 2] = 7; output_.packed[offset + 3] = 255;
        }
        if (!MapPackedUpload(output_)) return Status::NativeFailure;
        if (!Upload(depth_, device_, allocator_, list_, queue_, fence_, event_, fenceValue_)) return Status::NativeFailure;
        if (motionMode_ == static_cast<uint32_t>(dlssg::protocol::MotionMode::NvidiaOpticalFlow) &&
            !nvof_.Initialize(device_, queue_, width_, height_)) return Status::NativeFailure;
        SetCreateParameters(); if (!ResetList(allocator_, list_, "WORKER_CREATE")) return Status::NativeFailure;
        const NVSDK_NGX_Result result = create_(list_, NVSDK_NGX_Feature_FrameGeneration, parameters_, &feature_);
        RunLog("WORKER_CREATE_RESULT=0x%08X handle=%p", result, static_cast<void *>(feature_));
        if (NVSDK_NGX_FAILED(result) || !feature_ || FAILED(list_->Close())) return Status::NativeFailure;
        ID3D12CommandList *commands[] = {list_}; queue_->ExecuteCommandLists(1, commands);
        if (!WaitFence(queue_, fence_, ++fenceValue_, event_, device_, "WORKER_CREATE")) return Status::NativeFailure;
        created_ = true; history_.Reset(); ++createCount_;
        RunLog("WORKER_CREATE_COMPLETE createCount=%u feature=%p width=%u height=%u motionMode=%u",
            createCount_, static_cast<void *>(feature_), width_, height_, motionMode_);
        return Status::Ok;
    }

    Status Process(const dlssg::protocol::ProcessRequest &request, const uint8_t *color,
        const uint8_t *motion, dlssg::protocol::ProcessResponse &response,
        std::vector<uint8_t> &generated) {
        response = {}; response.width = width_; response.height = height_;
        response.pixelFormat = static_cast<uint32_t>(DXGI_FORMAT_R8G8B8A8_UNORM);
        if (!created_) return Status::InvalidState;
        bool effectiveReset = false;
        if (!history_.Begin(request.frameId, (request.flags & dlssg::protocol::ProcessFlagReset) != 0,
            effectiveReset)) return Status::InvalidFrameId;
        const auto totalStart = Clock::now(); const auto uploadStart = Clock::now();
        std::memcpy(color_.packed.data(), color, color_.packed.size());
        std::vector<uint8_t> internalMotion;
        NvofTimings nvofTimings{};
        // Normal rendering only needs the converted motion texture.  The full
        // distribution statistics allocate/sample on the CPU after the NVOF
        // readback and are deliberately reserved for the standalone
        // diagnostics harnesses.
        NvofFlowStatistics flowStatistics{};
        if (motionMode_ == static_cast<uint32_t>(dlssg::protocol::MotionMode::NvidiaOpticalFlow)) {
            if (effectiveReset) {
                internalMotion.assign(motion_.packed.size(), 0);
                if (nvof_.ForwardOnly() && !nvof_.SeedForward(color)) {
                    RunLog("WORKER_NVOF_SEED_FAILED frame=%llu", request.frameId); return Status::NativeFailure;
                }
            } else if (nvof_.ForwardOnly()
                ? !nvof_.ComputeForward(color, !nvofHistoryValid_, internalMotion, nullptr, nullptr, &nvofTimings)
                : previousColor_.size() != color_.packed.size() ||
                    !nvof_.ComputeBackward(previousColor_.data(), color, !nvofHistoryValid_, internalMotion,
                        nullptr, nullptr, &nvofTimings)) {
                RunLog("WORKER_NVOF_FAILED frame=%llu", request.frameId); return Status::NativeFailure;
            } else {
                nvofHistoryValid_ = true;
            }
            std::memcpy(motion_.packed.data(), internalMotion.data(), motion_.packed.size());
        } else {
            std::memcpy(motion_.packed.data(), motion, motion_.packed.size());
        }
        if (!UploadPair(color_, motion_, device_, allocator_, list_, queue_, fence_, event_, fenceValue_)) return Status::NativeFailure;
        const auto uploadEnd = Clock::now();
        if (!ResetList(allocator_, list_, "WORKER_EVALUATE")) return Status::NativeFailure;
        RecordDisableZero(disable_, list_); if (diagnosticMode_ || !effectiveReset) RecordTextureUpload(output_, list_, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        NVSDK_NGX_DLSSG_Opt_Eval_Params options{};
        if (!SetOptions(parameters_, color_.gpu, depth_.gpu, motion_.gpu, output_.gpu, disable_.gpu,
            effectiveReset, request.frameId, generatedPerGroup_, 1, options, false, width_, height_)) return Status::NativeFailure;
        const auto evaluateStart = Clock::now(); const NVSDK_NGX_Result evalResult = evaluate_(list_, feature_, parameters_, nullptr);
        const auto evaluateEnd = Clock::now(); ++evaluateCount_;
        RunLog("WORKER_EVALUATE frame=%llu reset=%d generatedCount=%u generatedIndex=1 result=0x%08X evaluateCount=%u", request.frameId,
            effectiveReset ? 1 : 0, generatedPerGroup_, evalResult, evaluateCount_);
        if (NVSDK_NGX_FAILED(evalResult) || FAILED(list_->Close())) return Status::NativeFailure;
        ID3D12CommandList *commands[] = {list_}; queue_->ExecuteCommandLists(1, commands); const auto waitStart = Clock::now();
        if (!WaitFence(queue_, fence_, ++fenceValue_, event_, device_, "WORKER_EVALUATE")) return Status::NativeFailure;
        const auto waitEnd = Clock::now();
        response.uploadMs = Milliseconds(uploadStart, uploadEnd); response.evaluateCpuMs = Milliseconds(evaluateStart, evaluateEnd);
        response.gpuWaitMs = Milliseconds(waitStart, waitEnd);
        response.nvofUploadMs = nvofTimings.uploadMs; response.nvofExecuteMs = nvofTimings.executeMs;
        response.flowConversionMs = nvofTimings.conversionMs;
        response.flowMeanX = flowStatistics.meanX; response.flowMeanY = flowStatistics.meanY;
        response.flowMedianX = flowStatistics.medianX; response.flowMedianY = flowStatistics.medianY;
        response.flowP95Magnitude = flowStatistics.p95Magnitude;
        response.flowMaximumMagnitude = flowStatistics.maximumMagnitude;
        response.flowStandardDeviationMagnitude = flowStatistics.standardDeviationMagnitude;
        response.flowNearZeroPercent = flowStatistics.nearZeroPercent;
        response.flowUnusuallyLargePercent = flowStatistics.unusuallyLargePercent;
        const auto readbackStart = Clock::now(); uint32_t disableValue = 0; std::vector<uint8_t> one;
        if (!Readback(output_, disable_, device_, allocator_, list_, queue_, fence_, event_, fenceValue_, one, disableValue)) return Status::NativeFailure;
        if (effectiveReset) {
            RunLog("WORKER_RESET_GROUP frame=%llu generatedCount=%u generatedIndex=1 disableValue=%u", request.frameId, generatedPerGroup_, disableValue);
            for (uint32_t index = 2; index <= generatedPerGroup_; ++index) {
                if (!ResetList(allocator_, list_, "WORKER_MFG_RESET_EVALUATE")) return Status::NativeFailure;
                RecordDisableZero(disable_, list_); if (diagnosticMode_) RecordTextureUpload(output_, list_, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                if (!SetOptions(parameters_, color_.gpu, depth_.gpu, motion_.gpu, output_.gpu, disable_.gpu,
                    true, request.frameId, generatedPerGroup_, index, options, false, width_, height_)) return Status::NativeFailure;
                const auto nextStart = Clock::now(); const NVSDK_NGX_Result next = evaluate_(list_, feature_, parameters_, nullptr);
                response.evaluateCpuMs += Milliseconds(nextStart, Clock::now()); ++evaluateCount_;
                RunLog("WORKER_EVALUATE frame=%llu reset=1 generatedCount=%u generatedIndex=%u result=0x%08X evaluateCount=%u", request.frameId, generatedPerGroup_, index, next, evaluateCount_);
                if (NVSDK_NGX_FAILED(next) || FAILED(list_->Close())) return Status::NativeFailure;
                queue_->ExecuteCommandLists(1, commands); const auto nextWait = Clock::now();
                if (!WaitFence(queue_, fence_, ++fenceValue_, event_, device_, "WORKER_MFG_RESET_EVALUATE")) return Status::NativeFailure;
                response.gpuWaitMs += Milliseconds(nextWait, Clock::now()); one.clear(); disableValue = 0;
                if (!Readback(output_, disable_, device_, allocator_, list_, queue_, fence_, event_, fenceValue_, one, disableValue)) return Status::NativeFailure;
                RunLog("WORKER_RESET_GROUP frame=%llu generatedCount=%u generatedIndex=%u disableValue=%u", request.frameId, generatedPerGroup_, index, disableValue);
            }
            history_.Complete(request.frameId);
            if (motionMode_ == static_cast<uint32_t>(dlssg::protocol::MotionMode::NvidiaOpticalFlow)) {
                if (!nvof_.ForwardOnly()) previousColor_.assign(color, color + color_.packed.size());
                nvofHistoryValid_ = false;
            }
            response.totalProcessMs = Milliseconds(totalStart, Clock::now());
            RunLog("WORKER_PROCESS_RESET_COMPLETE frame=%llu generatedCount=%u", request.frameId, generatedPerGroup_); return Status::OkResetNoOutput;
        }
        if (disableValue != 0) {
            RunLog("WORKER_OUTPUT_DISABLED frame=%llu reset=%d generatedCount=%u generatedIndex=1 disableValue=%u capabilityMax=%d evalResult=0x%08X deviceRemoved=0x%08X",
                request.frameId, effectiveReset ? 1 : 0, generatedPerGroup_, disableValue, capabilityMax_, evalResult,
                static_cast<unsigned>(device_->GetDeviceRemovedReason()));
            return Status::InterpolationDisabled;
        }
        const auto validOutput = [&](const std::vector<uint8_t> &value) {
            return (!diagnosticMode_ || value != output_.packed) && !std::all_of(value.begin(), value.end(), [](uint8_t item) { return item == 0; }) &&
                !( !value.empty() && std::all_of(value.begin(), value.end(), [&](uint8_t item) { return item == value.front(); }) );
        };
        if (!validOutput(one)) return Status::InvalidOutput;
        generated = one;
        for (uint32_t index = 2; index <= generatedPerGroup_; ++index) {
            if (!ResetList(allocator_, list_, "WORKER_MFG_EVALUATE")) return Status::NativeFailure;
            RecordDisableZero(disable_, list_); if (diagnosticMode_) RecordTextureUpload(output_, list_, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            if (!SetOptions(parameters_, color_.gpu, depth_.gpu, motion_.gpu, output_.gpu, disable_.gpu,
                false, request.frameId, generatedPerGroup_, index, options, false, width_, height_)) return Status::NativeFailure;
            const auto nextStart = Clock::now(); const NVSDK_NGX_Result next = evaluate_(list_, feature_, parameters_, nullptr);
            response.evaluateCpuMs += Milliseconds(nextStart, Clock::now()); ++evaluateCount_;
            RunLog("WORKER_EVALUATE frame=%llu reset=0 generatedCount=%u generatedIndex=%u result=0x%08X evaluateCount=%u", request.frameId, generatedPerGroup_, index, next, evaluateCount_);
            if (NVSDK_NGX_FAILED(next) || FAILED(list_->Close())) return Status::NativeFailure;
            queue_->ExecuteCommandLists(1, commands); const auto nextWait = Clock::now();
            if (!WaitFence(queue_, fence_, ++fenceValue_, event_, device_, "WORKER_MFG_EVALUATE")) return Status::NativeFailure;
            response.gpuWaitMs += Milliseconds(nextWait, Clock::now()); one.clear(); disableValue = 0;
            if (!Readback(output_, disable_, device_, allocator_, list_, queue_, fence_, event_, fenceValue_, one, disableValue)) return Status::NativeFailure;
            if (disableValue != 0) {
                RunLog("WORKER_OUTPUT_DISABLED frame=%llu reset=0 generatedCount=%u generatedIndex=%u disableValue=%u capabilityMax=%d evalResult=0x%08X deviceRemoved=0x%08X",
                    request.frameId, generatedPerGroup_, index, disableValue, capabilityMax_, next,
                    static_cast<unsigned>(device_->GetDeviceRemovedReason()));
                return Status::InterpolationDisabled;
            }
            if (!validOutput(one)) return Status::InvalidOutput;
            generated.insert(generated.end(), one.begin(), one.end());
        }
        const auto readbackEnd = Clock::now(); response.readbackMs = Milliseconds(readbackStart, readbackEnd);
        response.totalProcessMs = Milliseconds(totalStart, readbackEnd); response.disableInterpolation = 0;
        response.generatedCount = generatedPerGroup_; response.outputBytes = static_cast<uint32_t>(generated.size());
        history_.Complete(request.frameId);
        if (motionMode_ == static_cast<uint32_t>(dlssg::protocol::MotionMode::NvidiaOpticalFlow))
            if (!nvof_.ForwardOnly()) previousColor_.assign(color, color + color_.packed.size());
        generatedCount_ += generatedPerGroup_; RunLog("WORKER_OUTPUT frame=%llu outputs=%u sha256=%s generatedCount=%u totalMs=%.3f",
            request.frameId, generatedPerGroup_, Sha256(generated).c_str(), generatedCount_, response.totalProcessMs);
        return Status::Ok;
    }

    void ResetHistory() { history_.Reset(); previousColor_.clear(); nvofHistoryValid_ = false; RunLog("WORKER_HISTORY_RESET nextFrameForcedReset=1"); }
    uint32_t Width() const { return width_; }
    uint32_t Height() const { return height_; }
    uint32_t MotionMode() const { return motionMode_; }
    uint32_t InitCount() const { return initCount_; }
    uint32_t CreateCount() const { return createCount_; }
    uint32_t EvaluateCount() const { return evaluateCount_; }
    uint32_t GeneratedCount() const { return generatedCount_; }

private:
    bool DestroyFeatureAndResources() {
        nvof_.Shutdown();
        if (feature_) {
            const NVSDK_NGX_Result result = releaseFeature_(feature_);
            RunLog("WORKER_RELEASE_FEATURE_RESULT=0x%08X", result);
            if (NVSDK_NGX_FAILED(result)) return false;
            feature_ = nullptr;
        }
        ReleaseTexture(color_); ReleaseTexture(depth_); ReleaseTexture(motion_); ReleaseTexture(output_);
        ReleaseBuffer(disable_); created_ = false; previousColor_.clear(); nvofHistoryValid_ = false; history_.Reset();
        return true;
    }
    bool MapPackedUpload(Texture &texture) {
        uint8_t *mapped = nullptr; if (FAILED(texture.upload->Map(0, nullptr, reinterpret_cast<void **>(&mapped)))) return false;
        for (UINT row = 0; row < texture.height; ++row) std::memcpy(mapped + static_cast<size_t>(row) * texture.footprint.Footprint.RowPitch,
            texture.packed.data() + static_cast<size_t>(row) * texture.rowBytes, texture.rowBytes);
        texture.upload->Unmap(0, nullptr); return true;
    }
    void SetCreateParameters() {
        const unsigned always = NVSDK_NGX_DLSSG_ResourceFlags_Backbuffer | NVSDK_NGX_DLSSG_ResourceFlags_MVecs |
            NVSDK_NGX_DLSSG_ResourceFlags_Depth | NVSDK_NGX_DLSSG_ResourceFlags_HUDLess |
            NVSDK_NGX_DLSSG_ResourceFlags_OutputInterpolated | NVSDK_NGX_DLSSG_ResourceFlags_OutputDisableInterpolation;
        const unsigned never = NVSDK_NGX_DLSSG_ResourceFlags_UI | NVSDK_NGX_DLSSG_ResourceFlags_UIAlpha |
            NVSDK_NGX_DLSSG_ResourceFlags_BidirectionalDistortionField | NVSDK_NGX_DLSSG_ResourceFlags_OutputReal;
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_Parameter_CreationNodeMask, 1);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_Parameter_VisibilityNodeMask, 1);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_Parameter_Width, width_);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_Parameter_Height, height_);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_DLSSG_Parameter_Width, width_);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_DLSSG_Parameter_Height, height_);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_DLSSG_Parameter_BackbufferFormat, static_cast<unsigned>(DXGI_FORMAT_R8G8B8A8_UNORM));
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_DLSSG_Parameter_InternalWidth, width_);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_DLSSG_Parameter_InternalHeight, height_);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_DLSSG_Parameter_DynamicResolution, 0);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_DLSSG_Parameter_ResourceAlwaysProvided_Flags, always);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_DLSSG_Parameter_ResourceNeverProvided_Flags, never);
        NVSDK_NGX_Parameter_SetUI(parameters_, NVSDK_NGX_DLSSG_Parameter_UserInterfaceRecompositionEnabled, 0);
    }

    const char *projectId_ = "f8a17d65-4f1e-4e82-b0f2-4f6f93a7c8c1";
    IDXGIFactory6 *factory_ = nullptr; IDXGIAdapter1 *adapter_ = nullptr; DXGI_ADAPTER_DESC1 adapterDesc_{};
    ID3D12Device *device_ = nullptr; ID3D12CommandQueue *queue_ = nullptr;
    ID3D12CommandAllocator *allocator_ = nullptr; ID3D12GraphicsCommandList *list_ = nullptr; ID3D12Fence *fence_ = nullptr;
    HANDLE event_ = nullptr; UINT64 fenceValue_ = 0; NVSDK_NGX_FeatureCommonInfo common_{};
    std::wstring runtimeDir_{}; const wchar_t *runtimePaths_[1]{};
    NVSDK_NGX_Parameter *parameters_ = nullptr; HMODULE community_ = nullptr; InitFn init_ = nullptr;
    CreateFn create_ = nullptr; EvalFn evaluate_ = nullptr; ReleaseFeatureFn releaseFeature_ = nullptr;
    PopulateParametersFn populateParameters_ = nullptr; PopulateDeviceParametersFn populateDeviceParameters_ = nullptr;
    NVSDK_NGX_Handle *feature_ = nullptr;
    Texture color_{}, depth_{}, motion_{}, output_{}; Buffer disable_{}; HistoryState history_{};
    NvofD3D12 nvof_{}; std::vector<uint8_t> previousColor_{};
    bool nvofHistoryValid_ = false;
    bool diagnosticMode_ = false;
    uint32_t width_ = 0, height_ = 0, motionMode_ = 0, generatedPerGroup_ = 1;
    int capabilityMax_ = 1;
    bool created_ = false; uint32_t initCount_ = 0, createCount_ = 0, evaluateCount_ = 0, generatedCount_ = 0;
};

static bool ReadExact(HANDLE input, void *destination, uint32_t bytes) {
    auto *cursor = static_cast<uint8_t *>(destination); uint32_t remaining = bytes;
    while (remaining) { DWORD chunk = 0; if (!ReadFile(input, cursor, remaining, &chunk, nullptr) || chunk == 0) return false;
        cursor += chunk; remaining -= chunk; } return true;
}
static bool WriteExact(HANDLE output, const void *source, uint32_t bytes) {
    const auto *cursor = static_cast<const uint8_t *>(source); uint32_t remaining = bytes;
    while (remaining) { DWORD chunk = 0; if (!WriteFile(output, cursor, remaining, &chunk, nullptr) || chunk == 0) return false;
        cursor += chunk; remaining -= chunk; } return true;
}
static bool SendResponse(HANDLE output, const dlssg::protocol::RequestHeader &request, Status status,
    const void *payload = nullptr, uint32_t payloadBytes = 0) {
    const dlssg::protocol::ResponseHeader response{dlssg::protocol::kMagic, dlssg::protocol::kVersion,
        request.command, request.requestId, static_cast<int32_t>(status), payloadBytes};
    return WriteExact(output, &response, sizeof(response)) && (!payloadBytes || WriteExact(output, payload, payloadBytes));
}
} // namespace

bool WorkerProtocolSelfTest() {
    HistoryState history{}; bool reset = false;
    if (!history.Begin(0, false, reset) || !reset) return false; history.Complete(0);
    if (!history.Begin(1, false, reset) || reset) return false; history.Complete(1);
    if (history.Begin(1, false, reset)) return false; history.Reset();
    if (!history.Begin(2, false, reset) || !reset) return false;
    return sizeof(dlssg::protocol::RequestHeader) == 16 && sizeof(dlssg::protocol::ResponseHeader) == 20 &&
        sizeof(dlssg::protocol::ProcessResponse) == 160;
}

int RunServer(const wchar_t *communityPath, const wchar_t *runtimeDir) {
    RunLog("WORKER_PROCESS_ENTRY"); RunLog("WORKER_PROTOCOL_VERSION=%u", dlssg::protocol::kVersion);
    HANDLE input = GetStdHandle(STD_INPUT_HANDLE), output = GetStdHandle(STD_OUTPUT_HANDLE);
    if (!input || input == INVALID_HANDLE_VALUE || !output || output == INVALID_HANDLE_VALUE) return 70;
    PersistentWorker worker; if (!worker.Initialize(communityPath, runtimeDir)) return 71;
    for (;;) {
        dlssg::protocol::RequestHeader header{}; if (!ReadExact(input, &header, sizeof(header))) return 0;
        if (header.payloadBytes > dlssg::protocol::kMaximumPayloadBytes) return 72;
        std::vector<uint8_t> payload(header.payloadBytes);
        if (header.payloadBytes && !ReadExact(input, payload.data(), header.payloadBytes)) return 73;
        if (header.magic != dlssg::protocol::kMagic) { if (!SendResponse(output, header, Status::InvalidMessage)) return 74; continue; }
        if (header.version != dlssg::protocol::kVersion) { if (!SendResponse(output, header, Status::UnsupportedVersion)) return 74; continue; }
        const Command command = static_cast<Command>(header.command);
        if (command == Command::Hello) {
            const dlssg::protocol::HelloResponse hello{dlssg::protocol::kWorkerVersion, dlssg::protocol::kVersion, 1, 0};
            if (header.payloadBytes || !SendResponse(output, header, header.payloadBytes ? Status::InvalidPayloadSize : Status::Ok, &hello, sizeof(hello))) return 74;
        } else if (command == Command::Create) {
            if (payload.size() != sizeof(dlssg::protocol::CreateRequest)) { if (!SendResponse(output, header, Status::InvalidPayloadSize)) return 74; continue; }
            dlssg::protocol::CreateRequest request{}; std::memcpy(&request, payload.data(), sizeof(request)); dlssg::protocol::CreateResponse response{};
            const Status status = worker.Create(request, response); if (!SendResponse(output, header, status, &response, sizeof(response))) return 74;
        } else if (command == Command::Process) {
            if (payload.size() < sizeof(dlssg::protocol::ProcessRequest)) { if (!SendResponse(output, header, Status::InvalidPayloadSize)) return 74; continue; }
            dlssg::protocol::ProcessRequest request{}; std::memcpy(&request, payload.data(), sizeof(request));
            const uint64_t expected = sizeof(request) + static_cast<uint64_t>(request.colorBytes) + request.motionBytes + request.depthBytes;
            const uint64_t fixedBytes64 = static_cast<uint64_t>(worker.Width()) * worker.Height() * 4;
            const bool external = worker.MotionMode() == static_cast<uint32_t>(dlssg::protocol::MotionMode::ExternalR16G16Float);
            if (expected != payload.size() || fixedBytes64 > UINT32_MAX || request.colorBytes != fixedBytes64 ||
                request.motionBytes != (external ? fixedBytes64 : 0) || request.depthBytes != 0) {
                if (!SendResponse(output, header, Status::InvalidPayloadSize)) return 74; continue;
            }
            dlssg::protocol::ProcessResponse response{}; std::vector<uint8_t> generated;
            const uint8_t *color = payload.data() + sizeof(request); const uint8_t *motion = color + request.colorBytes;
            const Status status = worker.Process(request, color, motion, response, generated);
            std::vector<uint8_t> responsePayload(sizeof(response) + generated.size()); std::memcpy(responsePayload.data(), &response, sizeof(response));
            if (!generated.empty()) std::memcpy(responsePayload.data() + sizeof(response), generated.data(), generated.size());
            if (!SendResponse(output, header, status, responsePayload.data(), static_cast<uint32_t>(responsePayload.size()))) return 74;
        } else if (command == Command::ResetHistory) {
            if (header.payloadBytes) { if (!SendResponse(output, header, Status::InvalidPayloadSize)) return 74; continue; }
            worker.ResetHistory(); if (!SendResponse(output, header, Status::Ok)) return 74;
        } else if (command == Command::Close) {
            if (header.payloadBytes) { if (!SendResponse(output, header, Status::InvalidPayloadSize)) return 74; continue; }
            if (!SendResponse(output, header, Status::Ok)) return 74;
            RunLog("WORKER_CLOSE initCount=%u createCount=%u evaluateCount=%u generatedCount=%u",
                worker.InitCount(), worker.CreateCount(), worker.EvaluateCount(), worker.GeneratedCount());
            RunLog("WORKER_NGX_SHUTDOWN_SKIPPED_KNOWN_HANG=1"); std::fflush(stderr); ExitProcess(0);
        } else {
            if (!SendResponse(output, header, Status::InvalidMessage)) return 74;
        }
    }
}
