#include "ampere_bridge.h"
#include <array>
#include <chrono>
#include <fstream>
#include <vector>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <thread>
#include <psapi.h>
#include <bcrypt.h>

namespace ampere_bridge { namespace {
constexpr uint32_t INIT=0x0150e828, ENUM=0xe5ac921f, ADAPTER=0x0ff07fde, ARCH=0xd8265d24;
constexpr NvStatus OK=NVAPI_OK; constexpr size_t MAX_GPUS=NVAPI_MAX_PHYSICAL_GPUS; thread_local uint32_t depth=0;
Bridge *active=nullptr; std::mutex hook_lock; std::atomic_uint32_t hook_calls{0};
struct HookFaults { int flush_failures=0; int readback_failures=0; };
HookFaults *test_faults=nullptr;
bool Qualified(const PolicyState&s){return s.bridge_enabled&&!s.shutting_down&&s.ampere_backport&&s.exact_adapter&&s.exact_provider&&s.qualified_provider_count==1&&s.native_architecture==ampere_provider::kNativeArchitecture&&s.hook_installed;}
bool Executable(const void*p){MEMORY_BASIC_INFORMATION m{};return VirtualQuery(p,&m,sizeof(m))==sizeof(m)&&m.State==MEM_COMMIT&&(m.Protect&(PAGE_EXECUTE|PAGE_EXECUTE_READ|PAGE_EXECUTE_READWRITE|PAGE_EXECUTE_WRITECOPY));}
// This is deliberately an exact contract for the pinned RTX 3070 Ti/610.62
// machine. It is not a decoder and there is no fallback path. The 20 bytes are
// complete, position-independent instructions for the reviewed build.
constexpr uintptr_t kExpectedTargetRva = 0x18B7C0;
constexpr char kExpectedImplementationSha256[] = "C129247C3F70BFCA49D3F16B28A02D5EE115E541B9F375F154F481A45B35F087";
constexpr std::array<uint8_t, 20> kExpectedPrologue = {
    0x48, 0x89, 0x5C, 0x24, 0x18, 0x55, 0x56, 0x57,
    0x41, 0x56, 0x41, 0x57, 0x48, 0x8D, 0xAC, 0x24,
    0x70, 0xFF, 0xFF, 0xFF
};
bool ReadableRange(const void *address, size_t size) {
    auto p = static_cast<const uint8_t *>(address);
    MEMORY_BASIC_INFORMATION m{};
    if (VirtualQuery(p, &m, sizeof(m)) != sizeof(m) || m.State != MEM_COMMIT) return false;
    const DWORD readable = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
        PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    if ((m.Protect & readable) == 0 || p < static_cast<const uint8_t *>(m.BaseAddress)) return false;
    const auto remaining = static_cast<const uint8_t *>(m.BaseAddress) + m.RegionSize - p;
    return size <= static_cast<size_t>(remaining);
}
void AbsoluteJump(uint8_t (&out)[14], const void *destination) {
    out[0] = 0xFF; out[1] = 0x25; out[2] = out[3] = out[4] = out[5] = 0;
    const auto value = reinterpret_cast<uint64_t>(destination);
    memcpy(out + 6, &value, sizeof(value));
}
bool FlushChecked(void *where, size_t size) {
    if (test_faults && test_faults->flush_failures > 0) { --test_faults->flush_failures; return false; }
    return FlushInstructionCache(GetCurrentProcess(), where, size) != FALSE;
}
bool WriteAndVerify(void *where, const void *bytes, size_t size, bool &target_may_be_modified) {
    DWORD old = 0, restored = 0;
    if (!VirtualProtect(where, size, PAGE_EXECUTE_READWRITE, &old)) return false;
    target_may_be_modified = true;
    memcpy(where, bytes, size);
    const bool write_ok = !(test_faults && test_faults->readback_failures > 0 && (--test_faults->readback_failures, true)) && memcmp(where, bytes, size) == 0;
    const bool restore_call_ok = VirtualProtect(where, size, old, &restored);
    MEMORY_BASIC_INFORMATION current{};
    const bool restore_ok = restore_call_ok && VirtualQuery(where, &current, sizeof(current)) == sizeof(current) && current.Protect == old;
    const bool flush_ok = FlushChecked(where, size);
    return write_ok && restore_ok && flush_ok;
}
bool ExactOwner(void *target, HMODULE &retained) {
    HMODULE owner=nullptr; if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,reinterpret_cast<LPCWSTR>(target),&owner))return false;
    MODULEINFO info{}; if(!GetModuleInformation(GetCurrentProcess(),owner,&info,sizeof(info))){FreeLibrary(owner);return false;}
    auto base=reinterpret_cast<uint8_t*>(info.lpBaseOfDll); auto p=reinterpret_cast<uint8_t*>(target); if(p<base||static_cast<uintptr_t>(p-base)!=kExpectedTargetRva){FreeLibrary(owner);return false;}
    std::vector<wchar_t> path(32768);DWORD path_length=GetModuleFileNameW(owner,path.data(),static_cast<DWORD>(path.size())); if(!path_length||path_length>=path.size()){FreeLibrary(owner);return false;}
    const wchar_t *name=wcsrchr(path.data(),L'\\'); if(!name||_wcsicmp(name+1,L"nvapi64_impl.dll")!=0||info.SizeOfImage!=0x577000){FreeLibrary(owner);return false;}
    BCRYPT_ALG_HANDLE alg{};BCRYPT_HASH_HANDLE hash{};DWORD cb=0,obj=0;if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0){FreeLibrary(owner);return false;}bool ok=BCryptGetProperty(alg,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&obj),sizeof(obj),&cb,0)>=0;std::vector<uint8_t> ob(obj),digest(32);ok=ok&&BCryptCreateHash(alg,&hash,ob.data(),obj,nullptr,0,0)>=0;std::ifstream file(std::wstring(path.data(),path_length),std::ios::binary);std::vector<char> buffer(1<<16);while(ok&&file){file.read(buffer.data(),buffer.size());auto bytes_read=file.gcount();if(bytes_read)ok=BCryptHashData(hash,reinterpret_cast<PUCHAR>(buffer.data()),static_cast<ULONG>(bytes_read),0)>=0;}ok=ok&&BCryptFinishHash(hash,digest.data(),static_cast<ULONG>(digest.size()),0)>=0;if(hash)BCryptDestroyHash(hash);BCryptCloseAlgorithmProvider(alg,0);char text[65]{};for(size_t i=0;i<digest.size();++i)sprintf_s(text+i*2,3,"%02X",digest[i]);if(!ok||strcmp(text,kExpectedImplementationSha256)!=0){FreeLibrary(owner);return false;}retained=owner;return true;
}
bool RestoreExact(Bridge::HookState &state) {
    if (!state.target_may_be_modified) return true;
    bool changed=false; if (!WriteAndVerify(state.target,state.original.data(),20,changed)) return false;
    return memcmp(state.target,state.original.data(),20)==0;
}
bool Install(Bridge::HookState &state, void *target, void *replacement, bool synthetic_test = false) {
    std::lock_guard<std::mutex> guard(hook_lock);
    if (state.installed || state.fatal) return false;
    if (!synthetic_test && !ExactOwner(target,state.implementation_module)) return false;
    if (!ReadableRange(target, kExpectedPrologue.size()) || !Executable(target)) { if(state.implementation_module){FreeLibrary(state.implementation_module);state.implementation_module=nullptr;} return false; }
    std::array<uint8_t, 32> original{};
    if (!ReadableRange(target, original.size())) { if(state.implementation_module){FreeLibrary(state.implementation_module);state.implementation_module=nullptr;} return false; }
    memcpy(original.data(), target, original.size());
    if (memcmp(original.data(), kExpectedPrologue.data(), kExpectedPrologue.size()) != 0) return false;
    auto *trampoline = static_cast<uint8_t *>(VirtualAlloc(nullptr, 20 + 14, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    if (!trampoline) { if(state.implementation_module){FreeLibrary(state.implementation_module);state.implementation_module=nullptr;} return false; }
    memcpy(trampoline, original.data(), 20);
    uint8_t jump_back[14]{}; AbsoluteJump(jump_back, static_cast<uint8_t *>(target) + 20);
    memcpy(trampoline + 20, jump_back, sizeof(jump_back));
    DWORD ignored = 0;
    if (!VirtualProtect(trampoline, 34, PAGE_EXECUTE_READ, &ignored) ||
        !FlushInstructionCache(GetCurrentProcess(), trampoline, 34)) {
        VirtualFree(trampoline, 0, MEM_RELEASE); if(state.implementation_module){FreeLibrary(state.implementation_module);state.implementation_module=nullptr;} return false;
    }
    uint8_t patch[14]{}; AbsoluteJump(patch, replacement);
    std::array<uint8_t, 20> full_patch{}; memcpy(full_patch.data(),patch,14); for(size_t i=14;i<full_patch.size();++i)full_patch[i]=0x90;
    bool target_may=false;
    if (!WriteAndVerify(target, full_patch.data(), full_patch.size(), target_may) || memcmp(target, full_patch.data(), full_patch.size()) != 0) {
        state.target=target; state.trampoline=trampoline; state.stolen=20; memcpy(state.original.data(),original.data(),state.original.size()); state.target_may_be_modified=target_may;
        if (!RestoreExact(state)) { state.fatal=true; return false; }
        VirtualFree(trampoline, 0, MEM_RELEASE); if(state.implementation_module){FreeLibrary(state.implementation_module);state.implementation_module=nullptr;} state={}; return false;
    }
    state.target = target; state.trampoline = trampoline; state.stolen = 20;
    memcpy(state.original.data(), original.data(), state.original.size());
    memcpy(state.patch.data(), patch, state.patch.size()); state.target_may_be_modified = true; state.installed = true;
    return true;
}
bool Remove(Bridge::HookState &state, std::atomic_uint32_t &active_calls) {
    std::lock_guard<std::mutex> guard(hook_lock);
    if (!state.installed) return true;
    if (!RestoreExact(state) || memcmp(state.target, state.original.data(), 20) != 0) { state.fatal=true; return false; }
    const auto deadline = GetTickCount64() + 5000;
    while (active_calls.load(std::memory_order_acquire) != 0 && GetTickCount64() < deadline) Sleep(1);
    if (active_calls.load(std::memory_order_acquire) != 0) return false;
    if (!VirtualFree(state.trampoline, 0, MEM_RELEASE)) return false;
    if(state.implementation_module){FreeLibrary(state.implementation_module);state.implementation_module=nullptr;}
    state = {}; return true;
}
NvStatus HookedGetArchInfo(NvPhysicalGpuHandle gpu, NvGpuArchInfo *info) {
    ++hook_calls;
    return active ? active->GetArchInfo(gpu, info) : NVAPI_ERROR;
}
Bridge::HookState *synthetic_state = nullptr; std::atomic_uint32_t synthetic_hits{0};
NvStatus __cdecl SyntheticHook(NvPhysicalGpuHandle gpu, NvGpuArchInfo *info) {
    ++synthetic_hits;
    auto original = reinterpret_cast<NvGetArchInfo>(synthetic_state->trampoline);
    return original(gpu, info);
}
struct SyntheticLifetime { Bridge::HookState *state{}; std::atomic_uint32_t active{0}; std::atomic_bool entered{false}; std::atomic_bool release{false}; };
SyntheticLifetime *synthetic_lifetime=nullptr;
NvStatus __cdecl SyntheticBlockingHook(NvPhysicalGpuHandle gpu, NvGpuArchInfo *info) {
    auto *life=synthetic_lifetime; auto original=reinterpret_cast<NvGetArchInfo>(life->state->trampoline); const auto result=original(gpu,info);
    life->active.fetch_add(1,std::memory_order_acq_rel); life->entered.store(true,std::memory_order_release);
    while(!life->release.load(std::memory_order_acquire)) std::this_thread::yield();
    life->active.fetch_sub(1,std::memory_order_release); return result;
}
}
bool CanExposeArchitecture(const PolicyState&s,bool scope,NvPhysicalGpuHandle q,NvPhysicalGpuHandle b,NvStatus st,const NvGpuArchInfo*i){return Qualified(s)&&scope&&q&&q==b&&st==OK&&i;}
bool RunSyntheticHookTest(std::string &detail) {
    std::array<uint8_t, 64> code = {0x48,0x89,0x5C,0x24,0x18,0x55,0x56,0x57,0x41,0x56,0x41,0x57,0x48,0x8D,0xAC,0x24,0x70,0xFF,0xFF,0xFF,
        0x48,0x81,0xEC,0x90,0x01,0x00,0x00,0xB8,0x07,0x00,0x00,0x00,0x48,0x81,0xC4,0x90,0x01,0x00,0x00,0x41,0x5F,0x41,0x5E,0x5F,0x5E,0x5D,0x48,0x8B,0x5C,0x24,0x18,0xC3};
    auto *memory = static_cast<uint8_t *>(VirtualAlloc(nullptr, code.size(), MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE));
    if(!memory){detail="synthetic VirtualAlloc failed";return false;} memcpy(memory,code.data(),code.size()); DWORD old=0;
    if(!VirtualProtect(memory,code.size(),PAGE_EXECUTE_READ,&old)){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic executable protection failed";return false;}
    using Fn = NvStatus(__cdecl *)(NvPhysicalGpuHandle,NvGpuArchInfo*); auto fn=reinterpret_cast<Fn>(memory);NvGpuArchInfo info{};
    if(fn(nullptr,&info)!=7){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic original call failed";return false;}
    Bridge::HookState state{}; if(memcmp(memory,kExpectedPrologue.data(),kExpectedPrologue.size())!=0){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic fixture does not match exact contract";return false;} if(!Install(state,memory,reinterpret_cast<void*>(&SyntheticHook),true)){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic exact hook install failed";return false;}
    synthetic_state=&state; synthetic_hits=0; if(fn(nullptr,&info)!=7||synthetic_hits.load()!=1){synthetic_state=nullptr;Remove(state,synthetic_hits);VirtualFree(memory,0,MEM_RELEASE);detail="synthetic hook/original trampoline call failed";return false;}
    synthetic_state=nullptr; std::atomic_uint32_t no_active{0}; const bool removed=Remove(state,no_active); const auto restored_result=fn(nullptr,&info); const bool restored_bytes=memcmp(memory,code.data(),20)==0; if(!removed||restored_result!=7||!restored_bytes){VirtualFree(memory,0,MEM_RELEASE);detail=removed?"synthetic restored call/bytes failed":"synthetic removal protection/restore failed";return false;}
    code[0]^=1; DWORD writable=0; if(!VirtualProtect(memory,code.size(),PAGE_READWRITE,&writable)){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic mismatch setup failed";return false;} memcpy(memory,code.data(),code.size()); if(!VirtualProtect(memory,code.size(),PAGE_EXECUTE_READ,&writable)){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic mismatch protection failed";return false;} if(Install(state,memory,reinterpret_cast<void*>(&SyntheticHook),true)){Remove(state,no_active);VirtualFree(memory,0,MEM_RELEASE);detail="synthetic one-byte mismatch was accepted";return false;}
    code[0]^=1; if(!VirtualProtect(memory,code.size(),PAGE_READWRITE,&writable)){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic mismatch cleanup failed";return false;} memcpy(memory,code.data(),code.size()); if(!VirtualProtect(memory,code.size(),PAGE_EXECUTE_READ,&writable)){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic mismatch cleanup protection failed";return false;}
    // Exercise removal while a replacement is blocked. Remove must restore the
    // target, wait for active calls, and retain the trampoline until return.
    Bridge::HookState lifetime_state{}; SyntheticLifetime life{&lifetime_state}; synthetic_lifetime=&life;
    if(!Install(lifetime_state,memory,reinterpret_cast<void*>(&SyntheticBlockingHook),true)){synthetic_lifetime=nullptr;VirtualFree(memory,0,MEM_RELEASE);detail="synthetic active-call install failed";return false;}
    std::thread call([&]{if(fn(nullptr,&info)!=7) life.release.store(true);}); const auto enter_deadline=GetTickCount64()+1000; while(!life.entered.load(std::memory_order_acquire)&&GetTickCount64()<enter_deadline) std::this_thread::yield();
    if(!life.entered.load(std::memory_order_acquire)){life.release.store(true);call.join();synthetic_lifetime=nullptr;Remove(lifetime_state,life.active);VirtualFree(memory,0,MEM_RELEASE);detail="synthetic active-call did not enter replacement";return false;}
    bool removal_result=false; std::thread remover([&]{removal_result=Remove(lifetime_state,life.active);}); Sleep(10); const bool retained_while_active=lifetime_state.trampoline!=nullptr && lifetime_state.installed; life.release.store(true,std::memory_order_release); call.join(); remover.join(); synthetic_lifetime=nullptr;
    if(!removal_result||!retained_while_active||life.active.load()!=0||memcmp(memory,code.data(),20)!=0||lifetime_state.trampoline!=nullptr){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic active-call removal lifetime failed";return false;}
    // A post-write flush failure must restore all bytes before resources are freed.
    HookFaults faults{}; test_faults=&faults; Bridge::HookState failed{}; faults.readback_failures=1; const bool install_ok=Install(failed,memory,reinterpret_cast<void*>(&SyntheticHook),true); const bool bytes_after_failure=memcmp(memory,code.data(),20)==0; const bool retained_after_failure=failed.trampoline!=nullptr; const bool restored_after_failure=bytes_after_failure && !failed.installed && !retained_after_failure; test_faults=nullptr; if(install_ok||!restored_after_failure){detail="synthetic install-failure restoration failed (install="+std::to_string(install_ok)+", bytes="+std::to_string(bytes_after_failure)+", trampoline="+std::to_string(retained_after_failure)+")";VirtualFree(memory,0,MEM_RELEASE);return false;}
    // If restoration cannot be proven, resources remain intentionally retained.
    test_faults=&faults; Bridge::HookState poisoned{}; faults.readback_failures=2; const bool poisoned_ok=Install(poisoned,memory,reinterpret_cast<void*>(&SyntheticHook),true); test_faults=nullptr; if(poisoned_ok||!poisoned.fatal||poisoned.trampoline==nullptr||poisoned.installed){VirtualFree(memory,0,MEM_RELEASE);detail="synthetic unverified-restoration retention failed";return false;}
    VirtualFree(memory,0,MEM_RELEASE); detail="synthetic exact hook, mismatch, all-20-byte restoration, active-call lifetime, and failure retention passed"; return true;
}
bool CanNormalizeRequirements(const PolicyState&s,const RequirementsObservation&o){if(!Qualified(s)||!o.output_valid||o.feature!=NVSDK_NGX_Feature_FrameGeneration||static_cast<int>(o.result)!=static_cast<int>(NVSDK_NGX_Result_Success)||o.min_hw_architecture!=ampere_provider::kAdaArchitecture)return false;const auto supported=static_cast<uint32_t>(o.feature_supported);return supported==NVSDK_NGX_FeatureSupportResult_Supported||supported==NVSDK_NGX_FeatureSupportResult_AdapterUnsupported;}
bool CanEnableFrameGeneration(const PolicyState&s,const CapabilityObservation&o){return Qualified(s)&&static_cast<int>(o.result)==static_cast<int>(NVSDK_NGX_Result_Success)&&o.has_available&&o.available==0&&o.has_needs_updated_driver&&o.needs_updated_driver==0&&o.has_feature_init_result&&(o.feature_init_result==static_cast<int>(NVSDK_NGX_Result_Success)||o.feature_init_result==static_cast<int>(NVSDK_NGX_Result_FAIL_FeatureNotSupported));}
uint32_t NormalizedFrameCountMax(const CapabilityObservation&o,bool q){return !q||!o.has_multi_frame_count_max?static_cast<uint32_t>(o.multi_frame_count_max):o.multi_frame_count_max>1?1u:static_cast<uint32_t>(o.multi_frame_count_max);}
Scope::Scope(bool e):active_(e){if(active_)++depth;} Scope::~Scope(){if(active_&&depth)--depth;}
bool Bridge::Initialize(std::string&d){if(nvapi_){d="bridge already initialized";return false;}nvapi_=LoadLibraryExW(L"nvapi64.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(!nvapi_){d="System32 nvapi64.dll could not be loaded";return false;}auto q=reinterpret_cast<NvQueryInterface>(GetProcAddress(nvapi_,"nvapi_QueryInterface"));if(!q){d="nvapi_QueryInterface not found";Shutdown();return false;}auto init=reinterpret_cast<NvInitialize>(q(INIT));auto en=reinterpret_cast<NvEnumPhysicalGpus>(q(ENUM));auto aid=reinterpret_cast<NvGetAdapterId>(q(ADAPTER));original_get_arch_info_=reinterpret_cast<NvGetArchInfo>(q(ARCH));if(!init||!en||!aid||!original_get_arch_info_||init()!=OK){d="required NVAPI interface unavailable";Shutdown();return false;}policy_.bridge_enabled=true;d="System32 NVAPI loaded; detour pending provider qualification";return true;}
bool Bridge::BindAdapter(IDXGIAdapter*a,std::string&d){if(!policy_.bridge_enabled||!a){d="bridge or DXGI adapter unavailable";return false;}DXGI_ADAPTER_DESC x{};if(FAILED(a->GetDesc(&x))||x.VendorId!=0x10DE){d="selected adapter is not NVIDIA";return false;}binding_.adapter_luid=x.AdapterLuid;auto q=reinterpret_cast<NvQueryInterface>(GetProcAddress(nvapi_,"nvapi_QueryInterface"));auto en=reinterpret_cast<NvEnumPhysicalGpus>(q(ENUM));auto aid=reinterpret_cast<NvGetAdapterId>(q(ADAPTER));NvPhysicalGpuHandle h[MAX_GPUS]{};uint32_t n=0;if(!en||en(h,&n)!=OK||n>MAX_GPUS){d="NVAPI GPU enumeration failed";return false;}uint32_t matches=0;for(uint32_t i=0;i<n;++i){LUID l{};if(aid(h[i],&l)==OK&&l.LowPart==x.AdapterLuid.LowPart&&l.HighPart==x.AdapterLuid.HighPart){binding_.physical_gpu=h[i];binding_.nvapi_adapter_luid=l;++matches;}}if(matches!=1){d="full DXGI LUID did not identify exactly one NVAPI GPU";return false;}binding_.native_architecture.version=NV_GPU_ARCH_INFO_VER;if(original_get_arch_info_(binding_.physical_gpu,&binding_.native_architecture)!=OK||binding_.native_architecture.architecture!=ampere_provider::kNativeArchitecture){d="native architecture is not verified as 0x170";return false;}policy_.exact_adapter=true;policy_.native_architecture=binding_.native_architecture.architecture;return true;}
bool Bridge::PrepareProvider(const ampere_provider::Session&p,std::string&d){if(!policy_.exact_adapter||!p.qualified()||provider_prepared_){d="provider is not strictly qualified";return false;}if(!Install(hook_,reinterpret_cast<void*>(original_get_arch_info_),reinterpret_cast<void*>(&HookedGetArchInfo))){d="NVAPI target detour installation failed closed";return false;}active=this;provider_prepared_=true;policy_.exact_provider=true;policy_.qualified_provider_count=1;policy_.ampere_backport=true;policy_.hook_installed=true;ready_=true;return true;}
bool Bridge::PrepareArchitecturePreflight(std::string&d){if(!policy_.exact_adapter||provider_prepared_){d="architecture preflight adapter binding is not ready";return false;}policy_.exact_provider=true;policy_.qualified_provider_count=1;policy_.ampere_backport=true;if(!Install(hook_,reinterpret_cast<void*>(original_get_arch_info_),reinterpret_cast<void*>(&HookedGetArchInfo))){policy_.exact_provider=false;policy_.qualified_provider_count=0;policy_.ampere_backport=false;d="NVAPI architecture preflight detour installation failed";return false;}active=this;provider_prepared_=true;policy_.hook_installed=true;ready_=true;d="architecture preflight bridge installed";return true;}
bool Bridge::RemoveArchitecturePreflight(){const bool removed=Remove(hook_,active_calls_);if(removed){if(active==this)active=nullptr;provider_prepared_=false;policy_.hook_installed=false;policy_.exact_provider=false;policy_.qualified_provider_count=0;policy_.ampere_backport=false;ready_=false;}return removed;}
NvStatus Bridge::QueryNative(NvGpuArchInfo*i)const{if(!original_get_arch_info_||!binding_.physical_gpu||!i)return NVAPI_ERROR;i->version=NV_GPU_ARCH_INFO_VER;return original_get_arch_info_(binding_.physical_gpu,i);}
NvStatus Bridge::QueryBridged(NvGpuArchInfo*i){if(!i||!hook_.target)return NVAPI_ERROR;i->version=NV_GPU_ARCH_INFO_VER;EnableRequirementsScope();const auto entry=reinterpret_cast<NvGetArchInfo>(hook_.target);const NvStatus result=entry(binding_.physical_gpu,i);DisableRequirementsScope();return result;}
uint32_t Bridge::HookCallCountForTest() const { return hook_calls.load(std::memory_order_acquire); }
void Bridge::EnableRequirementsScope(){if(ready_)++depth;}void Bridge::DisableRequirementsScope(){if(depth)--depth;}
NvStatus Bridge::GetArchInfo(NvPhysicalGpuHandle g,NvGpuArchInfo*i)const{
    active_calls_.fetch_add(1, std::memory_order_acq_rel);
    struct Exit final { const Bridge *b; ~Exit(){ b->active_calls_.fetch_sub(1, std::memory_order_release); } } exit{this};
    auto fn=hook_.installed?reinterpret_cast<NvGetArchInfo>(hook_.trampoline):original_get_arch_info_;
    if(!fn)return NVAPI_ERROR;
    NvStatus s=fn(g,i);
    if(CanExposeArchitecture(policy_,depth!=0,g,binding_.physical_gpu,s,i))i->architecture=ampere_provider::kAdaArchitecture;
    return s;
}
NVSDK_NGX_Result Bridge::Requirements(IDXGIAdapter*a,const NVSDK_NGX_FeatureDiscoveryInfo*d,NVSDK_NGX_FeatureRequirement*o,RequirementsFn fn)const{if(!fn)return NVSDK_NGX_Result_Fail;DXGI_ADAPTER_DESC ad{};const bool exact_adapter=a&&SUCCEEDED(a->GetDesc(&ad))&&ad.AdapterLuid.LowPart==binding_.adapter_luid.LowPart&&ad.AdapterLuid.HighPart==binding_.adapter_luid.HighPart;Scope scope(Qualified(policy_)&&d&&d->FeatureID==NVSDK_NGX_Feature_FrameGeneration&&exact_adapter);auto r=fn(a,d,o);RequirementsObservation q{};q.feature=d?d->FeatureID:NVSDK_NGX_Feature_Reserved0;q.result=r;q.output_valid=o!=nullptr;q.feature_supported=o?o->FeatureSupported:NVSDK_NGX_FeatureSupportResult_Supported;q.min_hw_architecture=o?o->MinHWArchitecture:0;if(o!=nullptr&&CanNormalizeRequirements(policy_,q)){o->FeatureSupported=NVSDK_NGX_FeatureSupportResult_Supported;o->MinHWArchitecture=ampere_provider::kNativeArchitecture;}return r;}
NVSDK_NGX_Result Bridge::GetCapabilities(NVSDK_NGX_Parameter**out,CapabilitiesFn fn)const{if(!fn)return NVSDK_NGX_Result_Fail;auto r=fn(out);if(!out||!*out)return r;CapabilityObservation o{};o.result=r;int available=0;o.has_available=static_cast<int>((*out)->Get(NVSDK_NGX_Parameter_FrameGeneration_Available,&available))==static_cast<int>(NVSDK_NGX_Result_Success);o.available=static_cast<uint32_t>(available);o.has_needs_updated_driver=static_cast<int>((*out)->Get(NVSDK_NGX_Parameter_FrameGeneration_NeedsUpdatedDriver,&o.needs_updated_driver))==static_cast<int>(NVSDK_NGX_Result_Success);o.has_feature_init_result=static_cast<int>((*out)->Get(NVSDK_NGX_Parameter_FrameGeneration_FeatureInitResult,&o.feature_init_result))==static_cast<int>(NVSDK_NGX_Result_Success);o.has_multi_frame_count_max=static_cast<int>((*out)->Get(NVSDK_NGX_DLSSG_Parameter_MultiFrameCountMax,&o.multi_frame_count_max))==static_cast<int>(NVSDK_NGX_Result_Success);if(CanEnableFrameGeneration(policy_,o)){(*out)->Set(NVSDK_NGX_Parameter_FrameGeneration_Available,1);int v=0;if(static_cast<int>((*out)->Get(NVSDK_NGX_Parameter_FrameGeneration_Available,&v))!=static_cast<int>(NVSDK_NGX_Result_Success)||v!=1)return r;}return r;}
void Bridge::Shutdown(){
    policy_.shutting_down=true; ready_=false; provider_prepared_=false;
    policy_.exact_provider=false; policy_.qualified_provider_count=0;
    const bool removed=Remove(hook_,active_calls_);
    if(removed){ policy_.hook_installed=false; if(active==this)active=nullptr; original_get_arch_info_=nullptr;
        if(nvapi_){FreeLibrary(nvapi_);nvapi_=nullptr;} policy_={}; binding_={};
    } else {
        // The module and trampoline are intentionally retained until process exit.
        fprintf(stderr,"FATAL: NVAPI hook removal/lifetime could not be proven; retaining nvapi64.dll\n");
    }
}
}
