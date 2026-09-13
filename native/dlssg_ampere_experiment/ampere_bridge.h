#pragma once

#include <windows.h>
#include <dxgi.h>

#include <cstdint>
#include <atomic>
#include <array>
#include <string>

#include <nvsdk_ngx.h>
#include <nvsdk_ngx_defs_dlssg.h>
#include "ampere_provider.h"

namespace ampere_bridge {

using NvPhysicalGpuHandle = void *;
using NvStatus = int;
using NvQueryInterface = void *(__cdecl *)(uint32_t);
using NvInitialize = NvStatus(__cdecl *)();
using NvEnumPhysicalGpus = NvStatus(__cdecl *)(NvPhysicalGpuHandle *, uint32_t *);
using NvGetAdapterId = NvStatus(__cdecl *)(NvPhysicalGpuHandle, LUID *);

// The public NvAPI layout used by NvAPI_GPU_GetArchInfo. Only the fields needed
// by this bridge are named; the remaining fields are retained and never edited.
struct NvGpuArchInfo {
    uint32_t version = 0;
    uint32_t architecture = 0;
    uint32_t implementation = 0;
    uint32_t revision = 0;
    uint32_t gpu_id = 0;
    uint32_t sub_sys_id = 0;
    uint32_t sub_sys_vendor_id = 0;
    uint32_t reserved[9] = {};
};

using NvGetArchInfo = NvStatus(__cdecl *)(NvPhysicalGpuHandle, NvGpuArchInfo *);

struct ProviderQualification {
    bool exact_identity = false;
    bool layout_valid = false;
    bool memory_adapted = false;
    uint32_t count = 0;
};

struct PolicyState {
    bool bridge_enabled = false;
    bool ampere_backport = false;
    bool exact_adapter = false;
    bool exact_provider = false;
    uint32_t qualified_provider_count = 0;
    uint32_t native_architecture = 0;
    bool shutting_down = false;
    bool hook_installed = false;
};

struct RequirementsObservation {
    NVSDK_NGX_Feature feature = NVSDK_NGX_Feature_Reserved0;
    NVSDK_NGX_Result result = NVSDK_NGX_Result_Fail;
    NVSDK_NGX_Feature_Support_Result feature_supported = NVSDK_NGX_FeatureSupportResult_Supported;
    uint32_t min_hw_architecture = 0;
    bool output_valid = false;
};

struct CapabilityObservation {
    NVSDK_NGX_Result result = NVSDK_NGX_Result_Fail;
    uint32_t available = 0;
    int needs_updated_driver = 0;
    int feature_init_result = 0;
    int multi_frame_count_max = 0;
    bool has_needs_updated_driver = false;
    bool has_available = false;
    bool has_feature_init_result = false;
    bool has_multi_frame_count_max = false;
};

bool CanExposeArchitecture(const PolicyState &state, bool in_scope, NvPhysicalGpuHandle queried,
                           NvPhysicalGpuHandle bound, NvStatus original_status,
                           const NvGpuArchInfo *info);
bool CanNormalizeRequirements(const PolicyState &state, const RequirementsObservation &observation);
bool CanEnableFrameGeneration(const PolicyState &state, const CapabilityObservation &observation);
uint32_t NormalizedFrameCountMax(const CapabilityObservation &observation, bool qualified);
bool RunSyntheticHookTest(std::string &detail);

class Scope final {
public:
    explicit Scope(bool enabled);
    ~Scope();
    Scope(const Scope &) = delete;
    Scope &operator=(const Scope &) = delete;
private:
    bool active_ = false;
};

using RequirementsFn = NVSDK_NGX_Result(NVSDK_CONV *)(IDXGIAdapter *, const NVSDK_NGX_FeatureDiscoveryInfo *, NVSDK_NGX_FeatureRequirement *);
using CapabilitiesFn = NVSDK_NGX_Result(NVSDK_CONV *)(NVSDK_NGX_Parameter **);

struct Binding {
    LUID adapter_luid{};
    NvPhysicalGpuHandle physical_gpu = nullptr;
    NvGpuArchInfo native_architecture{};
    LUID nvapi_adapter_luid{};
};

class Bridge final {
public:
    struct HookState {
        void *target = nullptr;
        void *trampoline = nullptr;
        size_t stolen = 0;
        std::array<uint8_t, 32> original{};
        std::array<uint8_t, 14> patch{};
        bool installed = false;
        bool target_may_be_modified = false;
        bool fatal = false;
        HMODULE implementation_module = nullptr;
    };
    bool Initialize(std::string &detail);
    bool BindAdapter(IDXGIAdapter *adapter, std::string &detail);
    bool PrepareProvider(const ampere_provider::Session &provider, std::string &detail);
    void EnableRequirementsScope();
    void DisableRequirementsScope();
    void Shutdown();

    NVSDK_NGX_Result Requirements(IDXGIAdapter *adapter, const NVSDK_NGX_FeatureDiscoveryInfo *discovery,
                                  NVSDK_NGX_FeatureRequirement *out, RequirementsFn real_fn) const;
    NVSDK_NGX_Result GetCapabilities(NVSDK_NGX_Parameter **out, CapabilitiesFn real_fn) const;
    NvStatus GetArchInfo(NvPhysicalGpuHandle gpu, NvGpuArchInfo *info) const;
    bool HookInstalled() const { return hook_.installed; }
    uint32_t ActiveCallsForTest() const { return active_calls_.load(std::memory_order_acquire); }
    const Binding &binding() const { return binding_; }
    bool ready() const { return ready_; }

private:
    PolicyState policy_{};
    HMODULE nvapi_ = nullptr;
    NvGetArchInfo original_get_arch_info_ = nullptr;
    Binding binding_{};
    bool ready_ = false;
    bool provider_prepared_ = false;
    HookState hook_{};
    mutable std::atomic_uint32_t active_calls_{0};
};

} // namespace ampere_bridge
