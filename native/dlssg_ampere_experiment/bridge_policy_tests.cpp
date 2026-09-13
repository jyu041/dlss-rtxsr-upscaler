#include "ampere_bridge.h"

#include <cassert>

using namespace ampere_bridge;

int main() {
    std::string hook_detail; if(!RunSyntheticHookTest(hook_detail)){fprintf(stderr,"%s\n",hook_detail.c_str()); return 1;}
    PolicyState good{true, true, true, true, 1, ampere_provider::kNativeArchitecture, false, true};
    NvGpuArchInfo info{};
    int physical = 0;
    assert(CanExposeArchitecture(good, true, &physical, &physical, 0, &info));
    assert(!CanExposeArchitecture(good, false, &physical, &physical, 0, &info));
    assert(!CanExposeArchitecture(good, true, &physical, nullptr, 0, &info));
    assert(!CanExposeArchitecture(good, true, &physical, &physical, -1, &info));
    PolicyState shutdown = good; shutdown.shutting_down = true;
    assert(!CanExposeArchitecture(shutdown, true, &physical, &physical, 0, &info));

    RequirementsObservation req{};
    req.feature = NVSDK_NGX_Feature_FrameGeneration;
    req.result = NVSDK_NGX_Result_Success;
    req.feature_supported = NVSDK_NGX_FeatureSupportResult_AdapterUnsupported;
    req.min_hw_architecture = ampere_provider::kAdaArchitecture;
    req.output_valid = true;
    assert(CanNormalizeRequirements(good, req));
    req.feature = NVSDK_NGX_Feature_SuperSampling;
    assert(!CanNormalizeRequirements(good, req));
    req.feature = NVSDK_NGX_Feature_FrameGeneration;
    req.feature_supported = NVSDK_NGX_FeatureSupportResult_DriverVersionUnsupported;
    assert(!CanNormalizeRequirements(good, req));

    CapabilityObservation caps{};
    caps.result = NVSDK_NGX_Result_Success;
    caps.available = 0; caps.has_available = true;
    caps.has_needs_updated_driver = true;
    caps.needs_updated_driver = 0;
    caps.has_feature_init_result = true;
    caps.feature_init_result = static_cast<uint32_t>(NVSDK_NGX_Result_FAIL_FeatureNotSupported);
    caps.has_multi_frame_count_max = true;
    caps.multi_frame_count_max = 6;
    assert(CanEnableFrameGeneration(good, caps));
    assert(NormalizedFrameCountMax(caps, true) == 1);
    caps.needs_updated_driver = 1;
    assert(!CanEnableFrameGeneration(good, caps));
    caps.needs_updated_driver = 0;
    caps.feature_init_result = 0x12345678;
    assert(!CanEnableFrameGeneration(good, caps));
    assert(NormalizedFrameCountMax(caps, false) == 6);

    PolicyState two_providers = good;
    two_providers.qualified_provider_count = 2;
    assert(!CanEnableFrameGeneration(two_providers, caps));
    assert(!CanNormalizeRequirements(two_providers, req));
    caps.has_needs_updated_driver = false;
    assert(!CanEnableFrameGeneration(good, caps));
    caps.has_needs_updated_driver = true;
    caps.has_multi_frame_count_max = false;
    assert(NormalizedFrameCountMax(caps, true) == 6);
    caps.multi_frame_count_max = 0; caps.has_multi_frame_count_max = true;
    assert(NormalizedFrameCountMax(caps, true) == 0);
    return 0;
}
