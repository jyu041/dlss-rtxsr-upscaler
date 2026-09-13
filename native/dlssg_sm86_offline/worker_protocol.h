#pragma once

#include <cstdint>

namespace dlssg::protocol {

constexpr uint32_t kMagic = 0x47534C44u; // "DLSG" in little-endian byte order.
constexpr uint16_t kVersion = 2;
constexpr uint32_t kWorkerVersion = 2;
constexpr uint32_t kMaximumPayloadBytes = 64u * 1024u * 1024u;

enum class Command : uint16_t {
    Hello = 1,
    Create = 2,
    Process = 3,
    ResetHistory = 4,
    Close = 5,
};

enum class Status : int32_t {
    Ok = 0,
    OkResetNoOutput = 1,
    InvalidMessage = -1,
    UnsupportedVersion = -2,
    InvalidState = -3,
    InvalidDimensions = -4,
    InvalidFormat = -5,
    InvalidPayloadSize = -6,
    InvalidFrameId = -7,
    NativeFailure = -8,
    InterpolationDisabled = -9,
    InvalidOutput = -10,
};

enum class DepthMode : uint32_t {
    ConstantPointFive = 1,
    CallerR32Float = 2,
};

enum class MotionMode : uint32_t {
    ExternalR16G16Float = 1,
    NvidiaOpticalFlow = 2,
};

enum ProcessFlags : uint32_t {
    ProcessFlagReset = 1u << 0,
};

#pragma pack(push, 1)
struct RequestHeader {
    uint32_t magic;
    uint16_t version;
    uint16_t command;
    uint32_t requestId;
    uint32_t payloadBytes;
};

struct ResponseHeader {
    uint32_t magic;
    uint16_t version;
    uint16_t command;
    uint32_t requestId;
    int32_t status;
    uint32_t payloadBytes;
};

struct HelloResponse {
    uint32_t workerVersion;
    uint32_t protocolVersion;
    uint32_t capabilities;
    uint32_t reserved;
};

struct CreateRequest {
    uint32_t width;
    uint32_t height;
    uint32_t pixelFormat;
    uint32_t generatedCount;
    uint32_t depthMode;
    uint32_t motionMode;
};

struct CreateResponse {
    uint32_t workerVersion;
    uint32_t protocolVersion;
    uint32_t maximumGeneratedFrames;
    uint32_t depthMode;
};

struct ProcessRequest {
    uint64_t frameId;
    uint32_t flags;
    uint32_t colorBytes;
    uint32_t motionBytes;
    uint32_t depthBytes;
};

struct ProcessResponse {
    uint32_t generatedCount;
    uint32_t disableInterpolation;
    uint32_t width;
    uint32_t height;
    uint32_t pixelFormat;
    uint32_t outputBytes;
    double uploadMs;
    double evaluateCpuMs;
    double gpuWaitMs;
    double readbackMs;
    double totalProcessMs;
    double nvofUploadMs;
    double nvofExecuteMs;
    double flowConversionMs;
};
#pragma pack(pop)

static_assert(sizeof(RequestHeader) == 16);
static_assert(sizeof(ResponseHeader) == 20);
static_assert(sizeof(HelloResponse) == 16);
static_assert(sizeof(CreateRequest) == 24);
static_assert(sizeof(CreateResponse) == 16);
static_assert(sizeof(ProcessRequest) == 24);
static_assert(sizeof(ProcessResponse) == 88);

} // namespace dlssg::protocol
