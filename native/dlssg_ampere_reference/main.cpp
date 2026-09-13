// Phase 4A: COMMUNITY MFG REFERENCE HARNESS.
// No streaming protocol, child process, JSON loop, or downloaded community DLL.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdio>
#include <cstring>
#include <string_view>

#include "reference_core.hpp"

namespace {

void Stage(const char* text) {
    std::fprintf(stderr, "%s\n", text);
    std::fflush(stderr);
}

int SelfTest() {
    using namespace dlssg_ampere_reference;
    if (!IsArchitectureName("Ampere") || !IsAmpere(kNvidiaVendor, kAmpereArchitecture, 1) ||
        !IsProviderContract("310.2.1.0",
            "15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5") ||
        GeneratedFramesForMultiplier(2) != 1 ||
        !ValidateSyntheticPair(256, 256, 0.5f, -8.0f, 0.0f) ||
        !ValidatePtx89(".version 8.7\n.target sm_89\n") ||
        RetargetPtx89To86(".version 8.7\n.target sm_89\n") !=
            ".version 8.7\n.target sm_86\n" ||
        ValidatePtx89(".version 7.8\n.target sm_89\n") ||
        ValidateMixedFatbinOrder(true, true, true) == false ||
        ValidateMixedFatbinOrder(false, false, true)) {
        return 1;
    }
    Stage("SELFTEST_COMPLETE");
    return 0;
}

int LiveReference(std::string_view provider) {
    // Deliberately fail closed until the donor-derived provider publication and
    // NGX/D3D12 host are compiled against an installed NVIDIA NGX SDK. This
    // executable never loads a provider in this scaffold.
    if (provider.empty()) return 2;
    Stage("LIVE_REFERENCE_NOT_BUILT");
    return 2;
}

} // namespace

int main(int argc, char** argv) {
    Stage("PROCESS_ENTRY");
    if (argc < 2) {
        Stage("ARGS_PARSED");
        Stage("SELFTEST_COMPLETE");
        return 0;
    }
    if (std::strcmp(argv[1], "--selftest") == 0 && argc == 2) {
        Stage("ARGS_PARSED");
        return SelfTest();
    }
    if (std::strcmp(argv[1], "--run-2x") == 0 && argc == 3) {
        Stage("ARGS_PARSED");
        return LiveReference(argv[2]);
    }
    Stage("ARGS_PARSED");
    std::fprintf(stderr, "usage: dlssg_ampere_reference.exe --selftest | --run-2x <provider>\n");
    std::fflush(stderr);
    return 2;
}
