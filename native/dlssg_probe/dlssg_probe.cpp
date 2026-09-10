// Capability-only DLSS Frame Generation probe.
// This source intentionally does not create or evaluate any NGX feature.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>

#include <cstdint>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <nvsdk_ngx.h>
#include <nvsdk_ngx_defs_dlssg.h>

namespace fs = std::filesystem;

struct AdapterInfo {
    std::string name;
    std::string luid;
    uint64_t dedicated_memory = 0;
    bool software = false;
    IDXGIAdapter1 *adapter = nullptr;
};

template <typename T>
void release(T *&value) {
    if (value != nullptr) {
        value->Release();
        value = nullptr;
    }
}

std::string utf8(const wchar_t *value) {
    if (value == nullptr) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
    std::string result(size > 0 ? size - 1 : 0, '\0');
    if (size > 1) WideCharToMultiByte(CP_UTF8, 0, value, -1, result.data(), size - 1, nullptr, nullptr);
    return result;
}

std::string json_escape(const std::string &value) {
    std::ostringstream result;
    for (unsigned char character : value) {
        if (character == '"' || character == '\\') result << '\\' << character;
        else if (character == '\n') result << "\\n";
        else if (character == '\r') result << "\\r";
        else if (character == '\t') result << "\\t";
        else result << character;
    }
    return result.str();
}

std::string hex_result(NVSDK_NGX_Result result) {
    std::ostringstream value;
    value << "0x" << std::uppercase << std::hex << static_cast<uint32_t>(result);
    return value.str();
}

std::string hex_luid(const LUID &luid) {
    std::ostringstream value;
    value << std::uppercase << std::hex << std::setw(8) << std::setfill('0') << static_cast<uint32_t>(luid.HighPart)
          << std::setw(8) << std::setfill('0') << luid.LowPart;
    return value.str();
}

std::vector<AdapterInfo> enumerate_adapters(IDXGIFactory6 *factory) {
    std::vector<AdapterInfo> result;
    for (UINT index = 0;; ++index) {
        IDXGIAdapter1 *adapter = nullptr;
        if (factory->EnumAdapterByGpuPreference(index, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&adapter)) == DXGI_ERROR_NOT_FOUND) break;
        DXGI_ADAPTER_DESC1 description = {};
        if (SUCCEEDED(adapter->GetDesc1(&description))) {
            result.push_back({utf8(description.Description), hex_luid(description.AdapterLuid), description.DedicatedVideoMemory, (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0, adapter});
        } else {
            release(adapter);
        }
    }
    return result;
}

void print_adapters(const std::vector<AdapterInfo> &adapters) {
    std::cout << "\"adapters\":[";
    for (size_t index = 0; index < adapters.size(); ++index) {
        if (index) std::cout << ',';
        const auto &adapter = adapters[index];
        std::cout << "{\"index\":" << index << ",\"name\":\"" << json_escape(adapter.name)
                  << "\",\"luid\":\"" << adapter.luid << "\",\"dedicated_video_memory_mib\":"
                  << adapter.dedicated_memory / (1024 * 1024) << ",\"software\":" << (adapter.software ? "true" : "false") << '}';
    }
    std::cout << ']';
}

int main(int argc, char **argv) {
    if (argc != 3 || std::string(argv[1]) != "--runtime") {
        std::cerr << "Usage: dlssg_probe.exe --runtime <directory>\n";
        return 2;
    }
    const fs::path runtime = fs::absolute(fs::path(argv[2]));
    const fs::path library = runtime / "nvngx_dlssg.dll";
    if (!fs::is_regular_file(library)) {
        std::cerr << "Missing nvngx_dlssg.dll: " << library.string() << '\n';
        return 2;
    }

    SetEnvironmentVariableW(L"NGX_DISABLE_UPDATER", L"1");
    IDXGIFactory6 *factory = nullptr;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)))) {
        std::cerr << "CreateDXGIFactory2 failed\n";
        return 3;
    }
    auto adapters = enumerate_adapters(factory);
    std::vector<size_t> matches;
    for (size_t index = 0; index < adapters.size(); ++index) {
        if (!adapters[index].software && adapters[index].name == "NVIDIA GeForce RTX 3070") matches.push_back(index);
    }
    if (matches.size() != 1) {
        std::cout << "{\"probe_version\":1,";
        print_adapters(adapters);
        std::cout << ",\"error\":\"expected exactly one NVIDIA GeForce RTX 3070\"}\n";
        for (auto &adapter : adapters) release(adapter.adapter);
        release(factory);
        return 4;
    }

    const AdapterInfo &selected = adapters[matches[0]];
    ID3D12Device *device = nullptr;
    const HRESULT device_result = D3D12CreateDevice(selected.adapter, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device));
    if (FAILED(device_result)) {
        std::cout << "{\"probe_version\":1,";
        print_adapters(adapters);
        std::cout << ",\"error\":\"D3D12 device creation failed\"}\n";
        for (auto &adapter : adapters) release(adapter.adapter);
        release(factory);
        return 5;
    }

    const std::wstring runtime_wide = runtime.wstring();
    const wchar_t *paths[] = {runtime_wide.c_str()};
    NVSDK_NGX_FeatureCommonInfo feature_info = {};
    feature_info.PathListInfo.Path = paths;
    feature_info.PathListInfo.Length = 1;
    const NVSDK_NGX_Result init = NVSDK_NGX_D3D12_Init_with_ProjectID(
        "f8a17d65-4f1e-4e82-b0f2-4f6f93a7c8c1", NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0",
        runtime_wide.c_str(), device, &feature_info, NVSDK_NGX_Version_API);

    NVSDK_NGX_Parameter *parameters = nullptr;
    NVSDK_NGX_Result capability = static_cast<NVSDK_NGX_Result>(0);
    int available = 0;
    unsigned int maximum = 0;
    NVSDK_NGX_Result available_result = static_cast<NVSDK_NGX_Result>(0);
    NVSDK_NGX_Result maximum_result = static_cast<NVSDK_NGX_Result>(0);
    if (NVSDK_NGX_SUCCEED(init)) {
        capability = NVSDK_NGX_D3D12_GetCapabilityParameters(&parameters);
        if (NVSDK_NGX_SUCCEED(capability) && parameters != nullptr) {
            available_result = parameters->Get(NVSDK_NGX_Parameter_FrameGeneration_Available, &available);
            maximum_result = parameters->Get(NVSDK_NGX_DLSSG_Parameter_MultiFrameCountMax, &maximum);
        }
    }

    std::cout << "{\"probe_version\":1,";
    print_adapters(adapters);
    std::cout << ",\"selected_adapter_index\":" << matches[0] << ",\"adapter\":{\"name\":\"" << json_escape(selected.name)
              << "\",\"luid\":\"" << selected.luid << "\",\"dedicated_video_memory_mib\":" << selected.dedicated_memory / (1024 * 1024) << "},"
              << "\"ngx\":{\"init_result\":\"" << hex_result(init) << "\",\"capability_query_result\":\"" << hex_result(capability)
              << "\",\"frame_generation_available\":";
    if (NVSDK_NGX_SUCCEED(available_result)) std::cout << (available ? "true" : "false"); else std::cout << "null";
    std::cout << ",\"frame_generation_available_result\":\"" << hex_result(available_result) << "\",\"multi_frame_count_max\":";
    if (NVSDK_NGX_SUCCEED(maximum_result)) std::cout << maximum; else std::cout << "null";
    std::cout << ",\"multi_frame_count_max_result\":\"" << hex_result(maximum_result) << "\"}}\n";

    if (parameters != nullptr) NVSDK_NGX_D3D12_DestroyParameters(parameters);
    if (NVSDK_NGX_SUCCEED(init)) NVSDK_NGX_D3D12_Shutdown1(device);
    release(device);
    for (auto &adapter : adapters) release(adapter.adapter);
    release(factory);
    return NVSDK_NGX_SUCCEED(init) && NVSDK_NGX_SUCCEED(capability) ? 0 : 6;
}
