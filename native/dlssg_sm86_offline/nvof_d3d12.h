#pragma once

#include <cstdint>
#include <vector>

struct ID3D12Device;
struct ID3D12CommandQueue;

struct NvofFlowVector {
    float x;
    float y;
};

struct NvofTimings {
    double uploadMs = 0.0;
    double executeMs = 0.0;
    double readbackMs = 0.0;
    double conversionMs = 0.0;
};

struct NvofFlowStatistics {
    double meanX = 0.0;
    double meanY = 0.0;
    double medianX = 0.0;
    double medianY = 0.0;
    double p95Magnitude = 0.0;
    double maximumMagnitude = 0.0;
    double standardDeviationMagnitude = 0.0;
    double nearZeroPercent = 0.0;
    double unusuallyLargePercent = 0.0;
};

class NvofD3D12 {
public:
    NvofD3D12();
    ~NvofD3D12();
    NvofD3D12(const NvofD3D12 &) = delete;
    NvofD3D12 &operator=(const NvofD3D12 &) = delete;

    bool Initialize(ID3D12Device *device, ID3D12CommandQueue *queue, uint32_t width, uint32_t height);
    bool ComputeBackward(const uint8_t *previousRgba, const uint8_t *currentRgba,
        bool resetTemporalHints, std::vector<uint8_t> &motionR16G16Float,
        std::vector<NvofFlowVector> *flowPixels = nullptr,
        NvofFlowStatistics *statistics = nullptr, NvofTimings *timings = nullptr);
    void Shutdown();
    uint32_t Width() const;
    uint32_t Height() const;

private:
    struct Impl;
    Impl *impl_;
};

int RunNvofProbe();
int RunNvofFlowTest();
