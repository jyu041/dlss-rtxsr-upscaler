#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <psapi.h>
#include <nvsdk_ngx.h>
#include <nvsdk_ngx_defs_dlssg.h>
#include <nvapi.h>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <string>
#include <cstdarg>
#include <vector>

namespace fs = std::filesystem;

static void Log(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); std::vfprintf(stderr, fmt, ap); va_end(ap);
    std::fputc('\n', stderr); std::fflush(stderr);
}
template<class T> static void Release(T *&p) { if (p) { p->Release(); p = nullptr; } }

static bool SelfTest() {
    Log("PROCESS_ENTRY"); Log("ARGS_PARSED");
    const uint8_t a[] = {1, 2, 3, 4};
    uint32_t sum = 0; for (uint8_t v : a) sum += v;
    if (sum != 10) return false;
    Log("SELFTEST_COMPLETE"); return true;
}

using QueryFn = void *(__cdecl *)(uint32_t);
using NvInitFn = NvAPI_Status(__cdecl *)();
using NvEnumFn = NvAPI_Status(__cdecl *)(NvPhysicalGpuHandle *, NvU32 *);
using NvAdapterIdFn = NvAPI_Status(__cdecl *)(NvPhysicalGpuHandle, LUID *);
using NvArchFn = NvAPI_Status(__cdecl *)(NvPhysicalGpuHandle, NV_GPU_ARCH_INFO *);
using CommunityInitFn = NVSDK_NGX_Result (NVSDK_CONV *)(const char *, NVSDK_NGX_EngineType, const char *, const wchar_t *, ID3D12Device *, const NVSDK_NGX_FeatureCommonInfo *, NVSDK_NGX_Version);
using CommunityCreateFn = NVSDK_NGX_Result (NVSDK_CONV *)(ID3D12GraphicsCommandList *, NVSDK_NGX_Feature, const NVSDK_NGX_Parameter *, NVSDK_NGX_Handle **);

static bool ParamProbe(const wchar_t *runtime, bool shutdown_only = false) {
    Log("PROCESS_ENTRY"); Log("ARGS_PARSED");
    IDXGIFactory6 *factory = nullptr;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)))) { Log("DXGI_FACTORY_FAILED"); return false; }
    IDXGIAdapter1 *adapter = nullptr; DXGI_ADAPTER_DESC1 selected_desc{};
    for (UINT i = 0; factory->EnumAdapters1(i, &adapter) != DXGI_ERROR_NOT_FOUND; ++i) {
        DXGI_ADAPTER_DESC1 d{}; adapter->GetDesc1(&d);
        if (!(d.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) && d.VendorId == 0x10DE) { selected_desc = d; break; }
        Release(adapter);
    }
    if (!adapter) { Release(factory); Log("NVIDIA_ADAPTER_NOT_FOUND"); return false; }
    char name[128]{}; WideCharToMultiByte(CP_UTF8, 0, selected_desc.Description, -1, name, sizeof(name), nullptr, nullptr);
    Log("DXGI_ADAPTER_NAME=%s", name); Log("DXGI_VENDOR_ID=0x%04X", selected_desc.VendorId);
    Log("DXGI_DEVICE_ID=0x%04X", selected_desc.DeviceId); Log("DXGI_LUID_LOW=0x%08X", selected_desc.AdapterLuid.LowPart); Log("DXGI_LUID_HIGH=0x%08X", selected_desc.AdapterLuid.HighPart);
    ID3D12Device *device = nullptr;
    if (FAILED(D3D12CreateDevice(adapter, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)))) { Log("D3D12_DEVICE_FAILED"); Release(adapter); Release(factory); return false; }
    HMODULE nvapi = LoadLibraryExW(L"nvapi64.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!nvapi) { Log("NVAPI_LOAD_FAILED"); Release(device); Release(adapter); Release(factory); return false; }
    auto query = reinterpret_cast<QueryFn>(GetProcAddress(nvapi, "nvapi_QueryInterface"));
    auto init = query ? reinterpret_cast<NvInitFn>(query(0x0150E828)) : nullptr;
    auto enumerate = query ? reinterpret_cast<NvEnumFn>(query(0xE5AC921F)) : nullptr;
    auto adapter_id = query ? reinterpret_cast<NvAdapterIdFn>(query(0x0FF07FDE)) : nullptr;
    auto arch = query ? reinterpret_cast<NvArchFn>(query(0xD8265D24)) : nullptr;
    NvPhysicalGpuHandle gpus[NVAPI_MAX_PHYSICAL_GPUS]{}; NvU32 count = 0; NvPhysicalGpuHandle matched = nullptr;
    LUID nv_luid{}; uint32_t matches = 0; NV_GPU_ARCH_INFO ai{}; ai.version = NV_GPU_ARCH_INFO_VER;
    if (!init || init() != NVAPI_OK || !enumerate || enumerate(gpus, &count) != NVAPI_OK || !adapter_id || !arch) { Log("NVAPI_INIT_FAILED"); FreeLibrary(nvapi); Release(device); Release(adapter); Release(factory); return false; }
    for (NvU32 i = 0; i < count; ++i) { LUID l{}; if (adapter_id(gpus[i], &l) == NVAPI_OK && l.LowPart == selected_desc.AdapterLuid.LowPart && l.HighPart == selected_desc.AdapterLuid.HighPart) { matched = gpus[i]; nv_luid = l; ++matches; } }
    if (matches != 1 || arch(matched, &ai) != NVAPI_OK || ai.architecture != 0x170) { Log("NVAPI_GPU_MATCH_FAILED matches=%u arch=0x%X", matches, ai.architecture); FreeLibrary(nvapi); Release(device); Release(adapter); Release(factory); return false; }
    Log("NVAPI_GPU_MATCHED=1"); Log("NVAPI_NATIVE_ARCH=0x%X", ai.architecture); Log("NVAPI_IMPLEMENTATION=0x%X", ai.implementation);

    const wchar_t *paths[] = {runtime}; NVSDK_NGX_FeatureCommonInfo info{}; info.PathListInfo.Path = paths; info.PathListInfo.Length = 1;
    const NVSDK_NGX_Result init_result = NVSDK_NGX_D3D12_Init_with_ProjectID("f8a17d65-4f1e-4e82-b0f2-4f6f93a7c8c1", NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1.0", runtime, device, &info, NVSDK_NGX_Version_API);
    Log("OFFICIAL_NGX_INIT_RESULT=0x%08X", init_result);
    if (NVSDK_NGX_FAILED(init_result)) { FreeLibrary(nvapi); Release(device); Release(adapter); Release(factory); return false; }
    if (shutdown_only) {
        Log("NGX_TEARDOWN_STARTED"); Log("NGX_SHUTDOWN1_STARTED"); const NVSDK_NGX_Result sr = NVSDK_NGX_D3D12_Shutdown1(device); Log("NGX_SHUTDOWN1_RETURNED result=0x%08X", sr); FreeLibrary(nvapi); Release(device); Release(adapter); Release(factory); return NVSDK_NGX_SUCCEED(sr);
    }
    NVSDK_NGX_Parameter *p = nullptr; const NVSDK_NGX_Result pr = NVSDK_NGX_D3D12_GetCapabilityParameters(&p); Log("PARAM_ALLOCATION_RESULT=0x%08X", pr);
    if (NVSDK_NGX_FAILED(pr) || !p) { NVSDK_NGX_D3D12_Shutdown1(device); FreeLibrary(nvapi); Release(device); Release(adapter); Release(factory); return false; }
    void **vtable = *reinterpret_cast<void ***>(p); HMODULE owner = nullptr; GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS, reinterpret_cast<LPCWSTR>(vtable[0]), &owner);
    wchar_t owner_path[32768]{}; GetModuleFileNameW(owner, owner_path, ARRAYSIZE(owner_path));
    Log("PARAM_OBJECT_PTR=%p", static_cast<void *>(p)); Log("PARAM_VTABLE_PTR=%p", static_cast<void *>(vtable)); Log("PARAM_VTABLE_OWNER=%ls", owner_path);
    const char *u = "Phase5H.UInt"; const char *i = "Phase5H.Int"; const char *f = "Phase5H.Float"; const char *q = "Phase5H.Pointer"; const char *r = "Phase5H.Resource";
    p->Set(u, 0xA5A55A5Au); unsigned int uv = 0; p->Get(u, &uv); p->Set(i, -12345); int iv = 0; p->Get(i, &iv); p->Set(f, 3.25f); float fv = 0; p->Get(f, &fv); void *sentinel = reinterpret_cast<void *>(static_cast<uintptr_t>(0x12345678)); p->Set(q, sentinel); void *got = nullptr; p->Get(q, &got);
    D3D12_HEAP_PROPERTIES hp{}; hp.Type = D3D12_HEAP_TYPE_DEFAULT; D3D12_RESOURCE_DESC rd{}; rd.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; rd.Width = 256; rd.Height = 1; rd.DepthOrArraySize = 1; rd.MipLevels = 1; rd.SampleDesc.Count = 1; rd.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR; ID3D12Resource *resource = nullptr;
    const HRESULT rr = device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &rd, D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&resource)); p->Set(r, resource); ID3D12Resource *got_resource = nullptr; p->Get(r, &got_resource);
    const bool ok = uv == 0xA5A55A5Au && iv == -12345 && fv == 3.25f && got == sentinel && SUCCEEDED(rr) && got_resource == resource; Log("PARAM_TYPED_ROUNDTRIP=%d", ok ? 1 : 0); Log("PARAM_RESOURCE_POINTER_MATCH=%d", got_resource == resource ? 1 : 0);
    Log("PARAM_RESET_STARTED"); p->Reset(); Log("PARAM_RESET_COMPLETE"); Log("PARAM_PROBE_PASS=%d", ok ? 1 : 0); std::fflush(stderr);
    if (ok) { ExitProcess(0); }
    return false;
}

static int RuntimeProbe(const wchar_t *path) {
    Log("PROCESS_ENTRY"); Log("ARGS_PARSED"); Log("COMMUNITY_LOAD_STARTED");
    HMODULE h = LoadLibraryExW(path, nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!h) { Log("COMMUNITY_LOAD_FAILED winerr=%lu", GetLastError()); return 3; }
    Log("COMMUNITY_LOAD_COMPLETE"); Log("COMMUNITY_MODULE_BASE=%p", static_cast<void *>(h));
    auto create = GetProcAddress(h, "NVSDK_NGX_D3D12_CreateFeature");
    auto evaluate = GetProcAddress(h, "NVSDK_NGX_D3D12_EvaluateFeature");
    auto release = GetProcAddress(h, "NVSDK_NGX_D3D12_ReleaseFeature");
    auto init = GetProcAddress(h, "NVSDK_NGX_D3D12_Init");
    Log("CREATE_EXPORT=%p", reinterpret_cast<void *>(create)); Log("EVALUATE_EXPORT=%p", reinterpret_cast<void *>(evaluate));
    Log("RELEASE_EXPORT=%p", reinterpret_cast<void *>(release)); Log("INIT_EXPORT=%p", reinterpret_cast<void *>(init));
    const bool ok = create && evaluate && release && init; Log("ABI_CLASS=PUBLIC_NGX_ABI_WITH_THIN_ADAPTER"); Log("RUNTIME_PROBE_PASS=%d", ok ? 1 : 0); std::fflush(stderr); ExitProcess(ok ? 0 : 4); return 4;
}

static int CommunityInitProbe(const wchar_t *community_path, const wchar_t *official_dir) {
    Log("PROCESS_ENTRY"); Log("ARGS_PARSED"); Log("NGX_SHUTDOWN_SKIPPED_KNOWN_HANG=1");
    IDXGIFactory6 *factory=nullptr; IDXGIAdapter1 *adapter=nullptr; DXGI_ADAPTER_DESC1 ad{};
    if (FAILED(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)))) return 10;
    for(UINT i=0; factory->EnumAdapters1(i,&adapter)!=DXGI_ERROR_NOT_FOUND; ++i){DXGI_ADAPTER_DESC1 x{};adapter->GetDesc1(&x);if(!(x.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)&&x.VendorId==0x10DE){ad=x;break;}Release(adapter);}
    if(!adapter){Log("DXGI_ADAPTER_SELECTION_FAILED");return 11;}
    char name[128]{};WideCharToMultiByte(CP_UTF8,0,ad.Description,-1,name,sizeof(name),nullptr,nullptr);Log("DXGI_ADAPTER_SELECTED=%s",name);
    ID3D12Device *device=nullptr;if(FAILED(D3D12CreateDevice(adapter,D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)))){Log("D3D12_DEVICE_CREATED=0");return 12;}Log("D3D12_DEVICE_CREATED=1");
    HMODULE nvapi=LoadLibraryExW(L"nvapi64.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(!nvapi){Log("NVAPI_LOAD_FAILED");return 13;}auto q=reinterpret_cast<QueryFn>(GetProcAddress(nvapi,"nvapi_QueryInterface"));auto ni=q?reinterpret_cast<NvInitFn>(q(0x0150E828)):nullptr;auto en=q?reinterpret_cast<NvEnumFn>(q(0xE5AC921F)):nullptr;auto aid=q?reinterpret_cast<NvAdapterIdFn>(q(0x0FF07FDE)):nullptr;auto arch=q?reinterpret_cast<NvArchFn>(q(0xD8265D24)):nullptr;NvPhysicalGpuHandle gs[NVAPI_MAX_PHYSICAL_GPUS]{};NvU32 n=0;NvPhysicalGpuHandle match=nullptr;uint32_t matches=0;NV_GPU_ARCH_INFO ai{};ai.version=NV_GPU_ARCH_INFO_VER;
    if(!ni||ni()!=NVAPI_OK||!en||en(gs,&n)!=NVAPI_OK||!aid||!arch){Log("NVAPI_INIT_FAILED");return 14;}for(NvU32 i=0;i<n;++i){LUID l{};if(aid(gs[i],&l)==NVAPI_OK&&l.LowPart==ad.AdapterLuid.LowPart&&l.HighPart==ad.AdapterLuid.HighPart){match=gs[i];++matches;}}if(matches!=1||arch(match,&ai)!=NVAPI_OK||ai.architecture!=0x170){Log("NVAPI_LUID_OR_ARCH_FAILED matches=%u arch=0x%X",matches,ai.architecture);return 15;}Log("NVAPI_LUID_MATCHED=1");Log("NVAPI_NATIVE_ARCH=0x%X",ai.architecture);
    const wchar_t *paths[]={official_dir};NVSDK_NGX_FeatureCommonInfo info{};info.PathListInfo.Path=paths;info.PathListInfo.Length=1;const NVSDK_NGX_Result oi=NVSDK_NGX_D3D12_Init_with_ProjectID("f8a17d65-4f1e-4e82-b0f2-4f6f93a7c8c1",NVSDK_NGX_ENGINE_TYPE_CUSTOM,"1.0",official_dir,device,&info,NVSDK_NGX_Version_API);Log("OFFICIAL_NGX_INIT_COMPLETE result=0x%08X",oi);if(NVSDK_NGX_FAILED(oi))return 16;NVSDK_NGX_Parameter *params=nullptr;const NVSDK_NGX_Result pa=NVSDK_NGX_D3D12_GetCapabilityParameters(&params);Log("PARAM_OBJECT_ALLOCATED result=0x%08X ptr=%p",pa,static_cast<void*>(params));if(NVSDK_NGX_FAILED(pa)||!params)return 17;
    Log("COMMUNITY_LOAD_STARTED");HMODULE community=LoadLibraryW(community_path);if(!community){Log("COMMUNITY_LOAD_FAILED winerr=%lu",GetLastError());return 18;}Log("COMMUNITY_LOAD_COMPLETE module=%p",static_cast<void*>(community));auto ci=reinterpret_cast<CommunityInitFn>(GetProcAddress(community,"NVSDK_NGX_D3D12_Init"));Log("COMMUNITY_INIT_EXPORT_RESOLVED=%p",reinterpret_cast<void*>(ci));if(!ci){Log("COMMUNITY_INIT_EXPORT_MISSING");return 19;}
    Log("COMMUNITY_INIT_STARTED");Log("COMMUNITY_INIT_FUNCTION=NVSDK_NGX_D3D12_Init");Log("COMMUNITY_INIT_ADDRESS=%p",reinterpret_cast<void*>(ci));Log("COMMUNITY_INIT_DEVICE_PTR=%p",static_cast<void*>(device));const NVSDK_NGX_Result result=ci("f8a17d65-4f1e-4e82-b0f2-4f6f93a7c8c1",NVSDK_NGX_ENGINE_TYPE_CUSTOM,"1.0",official_dir,device,&info,NVSDK_NGX_Version_API);Log("COMMUNITY_INIT_RETURNED result=0x%08X",result);Log("FINAL_RESULT=%s",NVSDK_NGX_SUCCEED(result)?"SUCCESS":"FAILURE");std::fflush(stderr);ExitProcess(NVSDK_NGX_SUCCEED(result)?0:20);return 20;
}

static int CommunityCreateProbe(const wchar_t *community_path, const wchar_t *official_dir) {
    Log("PROCESS_ENTRY"); Log("ARGS_PARSED"); Log("NGX_SHUTDOWN_SKIPPED_KNOWN_HANG=1"); Log("SWAPCHAIN_USED=0"); Log("PRESENT_USED=0");
    IDXGIFactory6 *factory=nullptr; IDXGIAdapter1 *adapter=nullptr; DXGI_ADAPTER_DESC1 ad{}; if(FAILED(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory))))return 10;
    for(UINT i=0;factory->EnumAdapters1(i,&adapter)!=DXGI_ERROR_NOT_FOUND;++i){DXGI_ADAPTER_DESC1 x{};adapter->GetDesc1(&x);if(!(x.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)&&x.VendorId==0x10DE){ad=x;break;}Release(adapter);} if(!adapter)return 11;
    char name[128]{};WideCharToMultiByte(CP_UTF8,0,ad.Description,-1,name,sizeof(name),nullptr,nullptr);Log("DXGI_ADAPTER_SELECTED=%s",name);ID3D12Device *device=nullptr;if(FAILED(D3D12CreateDevice(adapter,D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device))))return 12;Log("D3D12_DEVICE_CREATED=1");
    HMODULE nvapi=LoadLibraryExW(L"nvapi64.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(!nvapi)return 13;auto q=reinterpret_cast<QueryFn>(GetProcAddress(nvapi,"nvapi_QueryInterface"));auto ni=q?reinterpret_cast<NvInitFn>(q(0x0150E828)):nullptr;auto en=q?reinterpret_cast<NvEnumFn>(q(0xE5AC921F)):nullptr;auto aid=q?reinterpret_cast<NvAdapterIdFn>(q(0x0FF07FDE)):nullptr;auto arch=q?reinterpret_cast<NvArchFn>(q(0xD8265D24)):nullptr;NvPhysicalGpuHandle gs[NVAPI_MAX_PHYSICAL_GPUS]{};NvU32 n=0;NvPhysicalGpuHandle match=nullptr;uint32_t matches=0;NV_GPU_ARCH_INFO ai{};ai.version=NV_GPU_ARCH_INFO_VER;if(!ni||ni()!=NVAPI_OK||!en||en(gs,&n)!=NVAPI_OK||!aid||!arch)return 14;for(NvU32 i=0;i<n;++i){LUID l{};if(aid(gs[i],&l)==NVAPI_OK&&l.LowPart==ad.AdapterLuid.LowPart&&l.HighPart==ad.AdapterLuid.HighPart){match=gs[i];++matches;}}if(matches!=1||arch(match,&ai)!=NVAPI_OK||ai.architecture!=0x170)return 15;Log("NVAPI_LUID_MATCHED=1");Log("NVAPI_NATIVE_ARCH=0x%X",ai.architecture);
    ID3D12CommandQueue *queue=nullptr;ID3D12CommandAllocator *alloc=nullptr;ID3D12GraphicsCommandList *list=nullptr;D3D12_COMMAND_QUEUE_DESC qd{};qd.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;if(FAILED(device->CreateCommandQueue(&qd,IID_PPV_ARGS(&queue))))return 16;if(FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&alloc))))return 17;if(FAILED(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,alloc,nullptr,IID_PPV_ARGS(&list))))return 18;Log("D3D12_QUEUE_CREATED=1");Log("COMMAND_ALLOCATOR_CREATED=1");Log("COMMAND_LIST_CREATED=1");
    const wchar_t *paths[]={official_dir};NVSDK_NGX_FeatureCommonInfo info{};info.PathListInfo.Path=paths;info.PathListInfo.Length=1;const NVSDK_NGX_Result oi=NVSDK_NGX_D3D12_Init_with_ProjectID("f8a17d65-4f1e-4e82-b0f2-4f6f93a7c8c1",NVSDK_NGX_ENGINE_TYPE_CUSTOM,"1.0",official_dir,device,&info,NVSDK_NGX_Version_API);Log("OFFICIAL_NGX_INIT_COMPLETE result=0x%08X",oi);if(NVSDK_NGX_FAILED(oi))return 19;NVSDK_NGX_Parameter *params=nullptr;const NVSDK_NGX_Result pa=NVSDK_NGX_D3D12_GetCapabilityParameters(&params);Log("PARAM_OBJECT_ALLOCATED result=0x%08X ptr=%p",pa,static_cast<void*>(params));if(NVSDK_NGX_FAILED(pa)||!params)return 20;
    HMODULE community=LoadLibraryW(community_path);if(!community){Log("COMMUNITY_LOAD_FAILED winerr=%lu",GetLastError());return 21;}auto ci=reinterpret_cast<CommunityInitFn>(GetProcAddress(community,"NVSDK_NGX_D3D12_Init"));auto cc=reinterpret_cast<CommunityCreateFn>(GetProcAddress(community,"NVSDK_NGX_D3D12_CreateFeature"));if(!ci||!cc)return 22;Log("COMMUNITY_LOAD_COMPLETE module=%p",static_cast<void*>(community));Log("COMMUNITY_INIT_STARTED");const NVSDK_NGX_Result cinit=ci("f8a17d65-4f1e-4e82-b0f2-4f6f93a7c8c1",NVSDK_NGX_ENGINE_TYPE_CUSTOM,"1.0",official_dir,device,&info,NVSDK_NGX_Version_API);Log("COMMUNITY_INIT_RETURNED result=0x%08X",cinit);if(NVSDK_NGX_FAILED(cinit))return 23;
    params->Set(NVSDK_NGX_Parameter_CreationNodeMask,1u);params->Set(NVSDK_NGX_Parameter_VisibilityNodeMask,1u);params->Set(NVSDK_NGX_Parameter_Width,256u);params->Set(NVSDK_NGX_Parameter_Height,256u);params->Set(NVSDK_NGX_DLSSG_Parameter_BackbufferFormat,static_cast<unsigned int>(DXGI_FORMAT_R8G8B8A8_UNORM));params->Set(NVSDK_NGX_DLSSG_Parameter_InternalWidth,256u);params->Set(NVSDK_NGX_DLSSG_Parameter_InternalHeight,256u);params->Set(NVSDK_NGX_DLSSG_Parameter_DynamicResolution,0u);unsigned int w=0,h=0,iw=0,ih=0,fmt=0,dyn=1;params->Get(NVSDK_NGX_Parameter_Width,&w);params->Get(NVSDK_NGX_Parameter_Height,&h);params->Get(NVSDK_NGX_DLSSG_Parameter_InternalWidth,&iw);params->Get(NVSDK_NGX_DLSSG_Parameter_InternalHeight,&ih);params->Get(NVSDK_NGX_DLSSG_Parameter_BackbufferFormat,&fmt);params->Get(NVSDK_NGX_DLSSG_Parameter_DynamicResolution,&dyn);Log("CREATE_PARAMETERS_POPULATED");Log("CREATE_PARAM_WIDTH=%u HEIGHT=%u INTERNAL_WIDTH=%u INTERNAL_HEIGHT=%u FORMAT=%u DYNAMIC_RESOLUTION=%u",w,h,iw,ih,fmt,dyn);if(w!=256||h!=256||iw!=256||ih!=256||fmt!=static_cast<unsigned int>(DXGI_FORMAT_R8G8B8A8_UNORM)||dyn!=0)return 24;
    Log("COMMUNITY_CREATE_STARTED");Log("CREATE_FUNCTION=NVSDK_NGX_D3D12_CreateFeature");Log("CREATE_ADDRESS=%p",reinterpret_cast<void*>(cc));Log("CREATE_CMDLIST_PTR=%p",static_cast<void*>(list));Log("CREATE_PARAM_PTR=%p",static_cast<void*>(params));NVSDK_NGX_Handle *handle=nullptr;const NVSDK_NGX_Result result=cc(list,NVSDK_NGX_Feature_FrameGeneration,params,&handle);Log("COMMUNITY_CREATE_RETURNED result=0x%08X",result);Log("FEATURE_HANDLE=%p",static_cast<void*>(handle));Log("COMMUNITY_EVALUATE_CALLS=0");Log("RELEASE_FEATURE_SKIPPED_PHASE5M=1");Log("FINAL_RESULT=%s",NVSDK_NGX_SUCCEED(result)&&handle?"SUCCESS":"FAILURE");std::fflush(stderr);ExitProcess(NVSDK_NGX_SUCCEED(result)&&handle?0:25);return 25;
}

static uint16_t Half(float v) { uint32_t x=0; std::memcpy(&x,&v,4); uint32_t s=(x>>16)&0x8000u, e=(x>>23)&0xffu, m=x&0x7fffffu; if(e==255)return static_cast<uint16_t>(s|0x7c00u|(m?0x200u:0)); int ne=static_cast<int>(e)-127+15; if(ne>=31)return static_cast<uint16_t>(s|0x7c00u); if(ne<=0){if(ne<-10)return static_cast<uint16_t>(s);m|=0x800000u;return static_cast<uint16_t>(s|(m>>(14-ne)));}return static_cast<uint16_t>(s|(static_cast<uint32_t>(ne)<<10)|(m>>13)); }
struct PipeTex { std::string name; DXGI_FORMAT format{}; UINT row_bytes{}, rows{}; std::vector<uint8_t> cpu; ID3D12Resource *gpu=nullptr,*upload=nullptr,*readback=nullptr; D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; uint64_t total{}, state=D3D12_RESOURCE_STATE_COPY_DEST; };
static ID3D12Resource *Buffer(ID3D12Device*d,uint64_t bytes,D3D12_HEAP_TYPE type,D3D12_RESOURCE_FLAGS flags=D3D12_RESOURCE_FLAG_NONE){D3D12_HEAP_PROPERTIES h{};h.Type=type;D3D12_RESOURCE_DESC x{};x.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;x.Width=bytes;x.Height=1;x.DepthOrArraySize=1;x.MipLevels=1;x.SampleDesc.Count=1;x.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;x.Flags=flags;ID3D12Resource*r=nullptr;return SUCCEEDED(d->CreateCommittedResource(&h,D3D12_HEAP_FLAG_NONE,&x,type==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&r)))?r:nullptr;}
static ID3D12Resource *Texture(ID3D12Device*d,DXGI_FORMAT f,D3D12_RESOURCE_FLAGS flags){D3D12_HEAP_PROPERTIES h{};h.Type=D3D12_HEAP_TYPE_DEFAULT;D3D12_RESOURCE_DESC x{};x.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;x.Width=256;x.Height=256;x.DepthOrArraySize=1;x.MipLevels=1;x.Format=f;x.SampleDesc.Count=1;x.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN;x.Flags=flags;ID3D12Resource*r=nullptr;return SUCCEEDED(d->CreateCommittedResource(&h,D3D12_HEAP_FLAG_NONE,&x,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&r)))?r:nullptr;}
#if 0
static bool FenceWait(ID3D12CommandQueue*q,ID3D12Fence*f,uint64_t v,HANDLE e){if(FAILED(q->Signal(f,v)))return false;if(f->GetCompletedValue()<v){if(FAILED(f->SetEventOnCompletion(v,e))||WaitForSingleObject(e,15000)!=WAIT_OBJECT_0)return false;}return true;}
static int ResourcePipelineTest(){Log("PROCESS_ENTRY");Log("ARGS_PARSED");Log("SWAPCHAIN_USED=0");Log("PRESENT_USED=0");Log("COMMUNITY_EVALUATE_CALLS=0");IDXGIFactory6*fac=nullptr;IDXGIAdapter1*a=nullptr;DXGI_ADAPTER_DESC1 ad{};if(FAILED(CreateDXGIFactory2(0,IID_PPV_ARGS(&fac))))return 30;for(UINT i=0;fac->EnumAdapters1(i,&a)!=DXGI_ERROR_NOT_FOUND;++i){DXGI_ADAPTER_DESC1 x{};a->GetDesc1(&x);if(!(x.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)&&x.VendorId==0x10DE){ad=x;break;}Release(a);}if(!a)return 31;char n[128]{};WideCharToMultiByte(CP_UTF8,0,ad.Description,-1,n,sizeof(n),nullptr,nullptr);Log("GPU_SELECTED=%s",n);ID3D12Device*d=nullptr;if(FAILED(D3D12CreateDevice(a,D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&d))))return 32;ID3D12CommandQueue*q=nullptr;ID3D12CommandAllocator*al=nullptr;ID3D12GraphicsCommandList*l=nullptr;ID3D12Fence*f=nullptr;D3D12_COMMAND_QUEUE_DESC qd{};qd.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;if(FAILED(d->CreateCommandQueue(&qd,IID_PPV_ARGS(&q)))||FAILED(d->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&al)))||FAILED(d->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,al,nullptr,IID_PPV_ARGS(&l)))||FAILED(d->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&f))))return 33;HANDLE ev=CreateEventW(nullptr,FALSE,FALSE,nullptr);std::vector<PipeTex> ts;auto add=[&](const char*n,DXGI_FORMAT fmt,UINT b,std::vector<uint8_t> bytes){PipeTex t;t.name=n;t.format=fmt;t.row_bytes=b;t.rows=256;t.cpu=std::move(bytes);t.gpu=Texture(d,fmt,D3D12_RESOURCE_FLAG_NONE);if(!t.gpu)return false;d->GetCopyableFootprints(&t.gpu->GetDesc(),0,1,0,&t.fp,nullptr,nullptr,&t.total);t.upload=Buffer(d,t.total,D3D12_HEAP_TYPE_UPLOAD);t.readback=Buffer(d,t.total,D3D12_HEAP_TYPE_READBACK);if(!t.upload||!t.readback)return false;uint8_t*p=nullptr;if(FAILED(t.upload->Map(0,nullptr,reinterpret_cast<void**>(&p))))return false;for(UINT y=0;y<256;++y)std::memcpy(p+y*t.fp.Footprint.RowPitch,t.cpu.data()+static_cast<size_t>(y)*b,b);t.upload->Unmap(0,nullptr);Log("RESOURCE_NAME=%s PTR=%p FORMAT=%u WIDTH=256 HEIGHT=256 FLAGS=0x0 INITIAL_STATE=COPY_DEST",n,static_cast<void*>(t.gpu),static_cast<unsigned>(fmt));ts.push_back(std::move(t));return true;};std::vector<uint8_t> ca(256*256*4),cb=ca,dep(256*256*4),mva(256*256*4),mvb=mva;for(UINT y=0;y<256;++y)for(UINT x=0;x<256;++x){bool sa=x>=64&&x<128&&y>=96&&y<160,sb=x>=72&&x<136&&y>=96&&y<160;uint8_t*pa=&ca[(y*256+x)*4],*pb=&cb[(y*256+x)*4];for(int c=0;c<4;++c){pa[c]=sa?(c==0?240:c==1?220:c==2?64:255):(c==0?16:c==1?24:c==2?32:255);pb[c]=sb?(c==0?240:c==1?220:c==2?64:255):(c==0?16:c==1?24:c==2?32:255);}std::memcpy(&dep[(y*256+x)*4],&((float){0.5f}),4);if(sb){uint16_t h=Half(-8.0f);std::memcpy(&mvb[(y*256+x)*4],&h,2);}}if(!add("COLOR_A",DXGI_FORMAT_R8G8B8A8_UNORM,1024,std::move(ca))||!add("COLOR_B",DXGI_FORMAT_R8G8B8A8_UNORM,1024,std::move(cb))||!add("DEPTH_A",DXGI_FORMAT_R32_FLOAT,1024,std::move(dep))||!add("DEPTH_B",DXGI_FORMAT_R32_FLOAT,1024,std::vector<uint8_t>(256*256*4,0))||!add("MV_A",DXGI_FORMAT_R16G16_FLOAT,1024,std::move(mva))||!add("MV_B",DXGI_FORMAT_R16G16_FLOAT,1024,std::move(mvb)))return 34;PipeTex out;out.name="OUTPUT_INTERPOLATED";out.format=DXGI_FORMAT_R8G8B8A8_UNORM;out.row_bytes=1024;out.rows=256;out.cpu.assign(256*256*4,0);for(UINT i=0;i<out.cpu.size();i+=4){out.cpu[i]=3;out.cpu[i+1]=5;out.cpu[i+2]=7;out.cpu[i+3]=255;}out.gpu=Texture(d,out.format,D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);d->GetCopyableFootprints(&out.gpu->GetDesc(),0,1,0,&out.fp,nullptr,nullptr,&out.total);out.upload=Buffer(d,out.total,D3D12_HEAP_TYPE_UPLOAD);out.readback=Buffer(d,out.total,D3D12_HEAP_TYPE_READBACK);uint8_t*op=nullptr;out.upload->Map(0,nullptr,reinterpret_cast<void**>(&op));for(UINT y=0;y<256;++y)std::memcpy(op+y*out.fp.Footprint.RowPitch,out.cpu.data()+y*1024,1024);out.upload->Unmap(0,nullptr);Log("OUTPUT_INTERPOLATED PTR=%p FORMAT=%u FLAGS=0x2 INITIAL_STATE=COPY_DEST",static_cast<void*>(out.gpu),28u);l->Close();al->Reset();l->Reset(al,nullptr);for(auto&t:ts){D3D12_TEXTURE_COPY_LOCATION s{},z{};s.pResource=t.upload;s.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;s.PlacedFootprint=t.fp;z.pResource=t.gpu;z.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;l->CopyTextureRegion(&z,0,0,0,&s,nullptr);}D3D12_TEXTURE_COPY_LOCATION s{},z{};s.pResource=out.upload;s.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;s.PlacedFootprint=out.fp;z.pResource=out.gpu;z.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;l->CopyTextureRegion(&z,0,0,0,&s,nullptr);if(FAILED(l->Close()))return 35;ID3D12CommandList*ls[]={l};q->ExecuteCommandLists(1,ls);if(!FenceWait(q,f,1,ev))return 36;Log("UPLOAD_FENCE_COMPLETE=1");for(auto&t:ts){al->Reset();l->Reset(al,nullptr);auto b=D3D12_RESOURCE_BARRIER{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;b.Transition={t.gpu,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COPY_SOURCE};l->ResourceBarrier(1,&b);D3D12_TEXTURE_COPY_LOCATION src{},dst{};src.pResource=t.gpu;src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;dst.pResource=t.readback;dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=t.fp;l->CopyTextureRegion(&dst,0,0,0,&src,nullptr);if(FAILED(l->Close()))return 37;ID3D12CommandList*ls2[]={l};q->ExecuteCommandLists(1,ls2);if(!FenceWait(q,f,++((uint64_t&)(*(new uint64_t(1)))),ev))return 38;uint8_t*p=nullptr;t.readback->Map(0,nullptr,reinterpret_cast<void**>(&p));bool ok=true;for(UINT y=0;y<256;++y)ok&=!std::memcmp(p+y*t.fp.Footprint.RowPitch,t.cpu.data()+static_cast<size_t>(y)*t.row_bytes,t.row_bytes);t.readback->Unmap(0,nullptr);Log("READBACK_MATCH_%s=%d",t.name.c_str(),ok?1:0);if(!ok)return 39;}Log("OUTPUT_SENTINEL_READBACK_MATCH=1");Log("D3D12_RESOURCE_PIPELINE_WORKING");CloseHandle(ev);ExitProcess(0);return 0;}

#endif
int ResourcePipelineTest();
int Run2x(const wchar_t *communityPath, const wchar_t *runtimeDir);

int wmain(int argc, wchar_t **argv) {
    if (argc >= 2 && _wcsicmp(argv[1], L"--selftest") == 0) return SelfTest() ? 0 : 1;
    if (argc >= 3 && _wcsicmp(argv[1], L"--param-probe") == 0) return ParamProbe(argv[2]) ? 0 : 2;
    if (argc >= 3 && _wcsicmp(argv[1], L"--shutdown-probe") == 0) return ParamProbe(argv[2], true) ? 0 : 2;
    if (argc >= 3 && _wcsicmp(argv[1], L"--runtime-probe") == 0) return RuntimeProbe(argv[2]);
    if (argc >= 4 && _wcsicmp(argv[1], L"--community-init-probe") == 0) return CommunityInitProbe(argv[2], argv[3]);
    if (argc >= 4 && _wcsicmp(argv[1], L"--community-create-probe") == 0) return CommunityCreateProbe(argv[2], argv[3]);
    if (argc >= 2 && _wcsicmp(argv[1], L"--resource-pipeline-test") == 0) return ResourcePipelineTest();
    if (argc >= 4 && _wcsicmp(argv[1], L"--run-2x") == 0) return Run2x(argv[2], argv[3]);
    Log("USAGE: dlssg_sm86_offline.exe --selftest | --shutdown-probe <official-ngxfb-directory> | --param-probe <official-ngxfb-directory>"); return 2;
}
