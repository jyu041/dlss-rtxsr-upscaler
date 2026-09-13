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

#include <algorithm>
#include <array>
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

struct Texture {
    const char *name = nullptr;
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    ID3D12Resource *gpu = nullptr, *upload = nullptr, *readback = nullptr;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT64 allocationBytes = 0;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
    std::vector<uint8_t> packed;
};
struct Buffer { ID3D12Resource *gpu = nullptr, *upload = nullptr, *readback = nullptr;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON; };

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
    D3D12_RESOURCE_FLAGS flags, D3D12_RESOURCE_STATES initialState) {
    texture.name = name; texture.format = format; texture.state = initialState;
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{}; desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = kWidth; desc.Height = kHeight; desc.DepthOrArraySize = 1; desc.MipLevels = 1;
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
    texture.packed.resize(static_cast<size_t>(kRowBytes) * kHeight);
    RunLog("RESOURCE_CREATED name=%s ptr=%p format=%u width=%u height=%u rowPitch=%u initialState=0x%X",
        name, static_cast<void *>(texture.gpu), static_cast<unsigned>(format), kWidth, kHeight,
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
    uint8_t *mapped = nullptr; const HRESULT mr = texture.upload->Map(0, nullptr, reinterpret_cast<void **>(&mapped));
    if (FAILED(mr)) { RunLog("UPLOAD_MAP_FAILED name=%s hr=0x%08X", texture.name, static_cast<unsigned>(mr)); return false; }
    for (UINT row = 0; row < kHeight; ++row) std::memcpy(mapped + static_cast<size_t>(row) * texture.footprint.Footprint.RowPitch,
        texture.packed.data() + static_cast<size_t>(row) * kRowBytes, kRowBytes);
    texture.upload->Unmap(0, nullptr); if (!ResetList(allocator, list, texture.name)) return false;
    D3D12_TEXTURE_COPY_LOCATION src{}, dst{}; src.pResource = texture.upload;
    src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint = texture.footprint;
    dst.pResource = texture.gpu; dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    Transition(list, texture.gpu, texture.state, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    texture.state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    const HRESULT cr = list->Close(); if (FAILED(cr)) { RunLog("UPLOAD_LIST_CLOSE_FAILED name=%s hr=0x%08X", texture.name, static_cast<unsigned>(cr)); return false; }
    ID3D12CommandList *commands[] = {list}; queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle, device, texture.name)) return false;
    RunLog("UPLOAD_COMPLETE name=%s finalState=0x%X fence=%llu", texture.name, static_cast<unsigned>(texture.state), fenceValue);
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

static bool SetOptions(NVSDK_NGX_Parameter *p, ID3D12Resource *color, ID3D12Resource *depth,
    ID3D12Resource *motion, ID3D12Resource *output, ID3D12Resource *disable, bool reset,
    unsigned long long frameId, NVSDK_NGX_DLSSG_Opt_Eval_Params &o, bool manifest) {
    o = {}; o.multiFrameCount = 1; o.multiFrameIndex = 1;
    Identity(o.cameraViewToClip); Identity(o.clipToCameraView); Identity(o.clipToLensClip);
    Identity(o.clipToPrevClip); Identity(o.prevClipToClip);
    o.mvecScale[0] = 1.0f / kWidth; o.mvecScale[1] = 1.0f / kHeight;
    o.cameraNear = 0.1f; o.cameraFar = 1000.0f; o.cameraFOV = 1.04719755f; o.cameraAspectRatio = 1.0f;
    o.reset = reset; o.orthoProjection = true; o.motionVectorsInvalidValue = -65500.0f;
    o.motionVectorsDilated = true; o.mvecsSubrectSize = {kWidth, kHeight};
    o.depthSubrectSize = {kWidth, kHeight}; o.hudLessSubrectSize = {kWidth, kHeight};
    o.backbufferSubrectSize = {kWidth, kHeight}; o.outputInterpSubrectSize = {kWidth, kHeight};

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
        RunLog("CREATE generic=256x256 dlssg=256x256 format=%u internal=256x256 dynamic=0", static_cast<unsigned>(DXGI_FORMAT_R8G8B8A8_UNORM));
        RunLog("EVAL FrameID=%llu type=ULL Reset=%u MultiFrameCount=1 MultiFrameIndex=1", frameId, reset ? 1u : 0u);
        RunLog("EVAL matrices=%p,%p,%p,%p,%p lifetime=CALLER_OWNED", static_cast<void *>(o.cameraViewToClip),
            static_cast<void *>(o.clipToCameraView), static_cast<void *>(o.clipToLensClip),
            static_cast<void *>(o.clipToPrevClip), static_cast<void *>(o.prevClipToClip));
        RunLog("EVAL jitter=0,0 mvecScale=%.9f,%.9f pinhole=0,0 near=%.3f far=%.3f fov=%.8f aspect=%.3f",
            o.mvecScale[0], o.mvecScale[1], o.cameraNear, o.cameraFar, o.cameraFOV, o.cameraAspectRatio);
        RunLog("EVAL HDR=0 DepthInverted=0 CameraMotionIncluded=0 AutoReset=0 NotRendering=0 Ortho=1 InvalidMV=%.1f Dilated=1 Menu=0", o.motionVectorsInvalidValue);
        RunLog("EVAL nonnullRects=mvec,depth,hudless,backbuffer,outputInterp base=0,0 size=256x256 nullRects=0,0/0x0");
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
    packed.resize(static_cast<size_t>(kRowBytes) * kHeight);
    for (UINT row = 0; row < kHeight; ++row) std::memcpy(packed.data() + static_cast<size_t>(row) * kRowBytes,
        mapped + static_cast<size_t>(row) * output.footprint.Footprint.RowPitch, kRowBytes);
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
    if (!SetOptions(parameters, colorA.gpu, depthA.gpu, motionA.gpu, output.gpu, disable.gpu, true, 0ULL, bootstrapOptions, true)) return 52;
    RunLog("BOOTSTRAP_EVALUATE_STARTED"); const NVSDK_NGX_Result bootstrapResult = evaluate(list, feature, parameters, nullptr);
    RunLog("BOOTSTRAP_EVALUATE_RESULT=0x%08X", bootstrapResult); if (NVSDK_NGX_FAILED(bootstrapResult)) return 53;
    if (FAILED(list->Close())) return 54; queue->ExecuteCommandLists(1, commands);
    if (!WaitFence(queue, fence, ++fenceValue, eventHandle, device, "BOOTSTRAP")) return 55; RunLog("BOOTSTRAP_FENCE_COMPLETE=1");

    NVSDK_NGX_DLSSG_Opt_Eval_Params measuredOptions{}; if (!ResetList(allocator, list, "MEASURED")) return 56;
    RecordDisableZero(disable, list); RecordTextureUpload(output, list, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    RunLog("OUTPUT_SENTINEL_PREFILLED sha256=%s", kSentinelSha);
    if (!SetOptions(parameters, colorB.gpu, depthB.gpu, motionB.gpu, output.gpu, disable.gpu, false, 1ULL, measuredOptions, false)) return 57;
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
