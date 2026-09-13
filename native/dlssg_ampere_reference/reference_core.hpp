// Phase 4A reference harness.
// Adapted from MFGAmpereUnlock-RenoDx (MIT), commit c88b208e3f8f12e86a261f06aef1da3a77adef27.
// This file keeps only donor-derived pure policy needed by the standalone host.
#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace dlssg_ampere_reference {

inline constexpr uint32_t kNvidiaVendor = 0x10de;
inline constexpr uint32_t kAmpereArchitecture = 0x170;
inline constexpr uint32_t kAdaArchitecture = 0x190;

struct ArchitectureProfile {
    uint32_t native_architecture;
    uint32_t exposed_architecture;
    uint32_t target_sm;
};

inline constexpr ArchitectureProfile kAmpere{ kAmpereArchitecture, kAdaArchitecture, 86 };

inline bool IsAmpere(uint32_t vendor, uint32_t architecture, uint32_t implementation) noexcept {
    // Donor rule: 0x170 is the Ampere family; implementation zero is rejected
    // because GA100 is SM80 and is outside the reviewed SM86 route.
    return vendor == kNvidiaVendor && architecture == kAmpereArchitecture && implementation != 0;
}

inline bool IsArchitectureName(std::string_view value) noexcept {
    return value == "Ampere" || value == "ampere" || value == "AMPERE";
}

inline bool IsProviderContract(std::string_view version, std::string_view sha256) noexcept {
    return version == "310.2.1.0" && sha256 ==
        "15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5";
}

inline unsigned GeneratedFramesForMultiplier(unsigned multiplier) noexcept {
    return multiplier >= 2 && multiplier <= 4 ? multiplier - 1 : 0;
}

inline bool ValidateSyntheticPair(unsigned width, unsigned height, float depth,
                                  float motion_x, float motion_y) noexcept {
    return width == 256 && height == 256 && depth == 0.5f &&
           motion_x == -8.0f && motion_y == 0.0f;
}

// Donor-derived PTX admission rule. The real donor additionally validates the
// enclosing CUDA fatbin and LZ4 literal provenance; this pure layer exercises
// the same fail-closed source-level contract without touching NVIDIA files.
inline bool ValidatePtx89(std::string_view ptx) noexcept {
    const size_t target = ptx.find(".target sm_89");
    if (target == std::string_view::npos || ptx.find(".target sm_89", target + 1) != std::string_view::npos)
        return false;
    const size_t version = ptx.find(".version 8.");
    return version != std::string_view::npos && version + 11 < ptx.size() &&
           ptx[version + 11] >= '0' && ptx[version + 11] <= '7';
}

inline std::string RetargetPtx89To86(std::string_view ptx) {
    if (!ValidatePtx89(ptx)) return {};
    std::string result(ptx);
    const size_t target = result.find(".target sm_89");
    result[target + 12] = '6';
    return result;
}

inline bool ValidateMixedFatbinOrder(bool hasAdaPtx, bool hasAmperePtx,
                                     bool hasTrailingAdaCubin) noexcept {
    // Reviewed donor layouts permit an Ada PTX before the target PTX and an
    // Ada cubin after it only when the latter can be hidden by truncation.
    return hasAmperePtx && (!hasTrailingAdaCubin || hasAdaPtx);
}

} // namespace dlssg_ampere_reference
