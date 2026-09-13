#include "ampere_provider.h"
#include "provider_transaction.h"
#include "provider_memory.h"
#include "donor_lz4.hpp"

#include <bcrypt.h>
#include <psapi.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <fstream>
#include <sstream>
#include <tuple>

#pragma comment(lib, "bcrypt.lib")

namespace ampere_provider {
namespace {
uint16_t U16(const uint8_t* p) { uint16_t v; memcpy(&v,p,2); return v; }
uint32_t U32(const uint8_t* p) { uint32_t v; memcpy(&v,p,4); return v; }
uint64_t U64(const uint8_t* p) { uint64_t v; memcpy(&v,p,8); return v; }
bool Bounds(const uint8_t* base, size_t n, const uint8_t* p, size_t s) { return p >= base && static_cast<size_t>(p-base) <= n && s <= n-static_cast<size_t>(p-base); }
bool MappedReadable(const uint8_t *base, size_t size, const void* expected_allocation) {
  size_t offset = 0;
  while (offset < size) {
    MEMORY_BASIC_INFORMATION m{};
    if (VirtualQuery(base + offset, &m, sizeof(m)) != sizeof(m) || m.State != MEM_COMMIT) return false;
    if (expected_allocation && m.AllocationBase != expected_allocation) return false;
    if (!memory::IsReadableProtection(m.Protect)) return false;
    const auto begin = reinterpret_cast<uintptr_t>(m.BaseAddress);
    const auto current = reinterpret_cast<uintptr_t>(base + offset);
    if (!memory::RegionCovers(current, begin, m.RegionSize, size - offset)) return false;
    offset = size;
  }
  return true;
}
bool BuildReadableShadow(const uint8_t* image, size_t image_size,
                          std::vector<uint8_t>& shadow) {
  shadow.assign(image_size, 0);
  size_t offset = 0;
  while (offset < image_size) {
    MEMORY_BASIC_INFORMATION m{};
    if (VirtualQuery(image + offset, &m, sizeof(m)) != sizeof(m) ||
        m.AllocationBase != image || m.RegionSize == 0) return false;
    const auto begin = reinterpret_cast<uintptr_t>(m.BaseAddress);
    const auto current = reinterpret_cast<uintptr_t>(image + offset);
    if (current < begin) return false;
    const size_t available = static_cast<size_t>(m.RegionSize - (current - begin));
    const size_t span = (available < image_size - offset) ? available : (image_size - offset);
    if (m.State == MEM_COMMIT && memory::IsReadableProtection(m.Protect))
      memcpy(shadow.data() + offset, image + offset, span);
    offset += span;
  }
  return true;
}
bool ProtectionIs(const void *address, DWORD expected) { MEMORY_BASIC_INFORMATION m{}; return VirtualQuery(address, &m, sizeof(m))==sizeof(m) && m.Protect==expected; }

bool Sha256(const std::wstring& path, std::string& out) {
  std::ifstream f(path, std::ios::binary); if (!f) return false;
  BCRYPT_ALG_HANDLE alg{}; BCRYPT_HASH_HANDLE hash{}; DWORD cb=0, obj=0;
  if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0) return false;
  bool ok = BCryptGetProperty(alg, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&obj), sizeof(obj), &cb, 0) >= 0;
  std::vector<uint8_t> object(obj), digest(32); ok = ok && BCryptCreateHash(alg,&hash,object.data(),obj,nullptr,0,0)>=0;
  std::vector<char> buf(1<<16); while(ok && f){ f.read(buf.data(),buf.size()); auto got=f.gcount(); if(got) ok=BCryptHashData(hash,reinterpret_cast<PUCHAR>(buf.data()),static_cast<ULONG>(got),0)>=0; }
  ok = ok && BCryptFinishHash(hash,digest.data(),static_cast<ULONG>(digest.size()),0)>=0; if(hash) BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(alg,0);
  if(!ok) return false; std::ostringstream s; for(auto b:digest) s<<std::hex<<std::uppercase<<static_cast<int>(b>>4)<<static_cast<int>(b&15); out=s.str(); return true;
}

bool Add(Edit& e, uint8_t* a, uint8_t before, uint8_t after) { if(*a!=before) return false; e={a,before,after}; return true; }
bool Canonical(const std::wstring& input, std::wstring& output) { std::vector<wchar_t> buf(32768); DWORD n=GetFullPathNameW(input.c_str(),static_cast<DWORD>(buf.size()),buf.data(),nullptr); if(!n||n>=buf.size()) return false; output.assign(buf.data(),n); return true; }
bool FileVersionExact(const std::wstring& path) { DWORD dummy=0,n=GetFileVersionInfoSizeW(path.c_str(),&dummy); if(!n)return false;std::vector<uint8_t>b(n);if(!GetFileVersionInfoW(path.c_str(),0,n,b.data()))return false;VS_FIXEDFILEINFO*f=nullptr;UINT len=0;if(!VerQueryValueW(b.data(),L"\\",reinterpret_cast<void**>(&f),&len)||!f)return false;char v[64]{};sprintf_s(v,"%u.%u.%u.%u",HIWORD(f->dwFileVersionMS),LOWORD(f->dwFileVersionMS),HIWORD(f->dwFileVersionLS),LOWORD(f->dwFileVersionLS));return strcmp(v,kExpectedVersion)==0; }
bool Lz4(const uint8_t* src, size_t sn, uint8_t* dst, size_t dn,
         size_t wanted, size_t* literal) {
  size_t in = 0;
  size_t out = 0;
  if (literal != nullptr) *literal = SIZE_MAX;
  auto extend = [&](size_t& length) {
    if (length != 15) return true;
    unsigned int extra = 0;
    do {
      if (in == sn) return false;
      extra = src[in++];
      if (length > dn || extra > dn - length) return false;
      length += extra;
    } while (extra == 255);
    return true;
  };
  while (in < sn) {
    const unsigned int token = src[in++];
    size_t length = token >> 4;
    if (!extend(length) || length > sn - in || length > dn - out) return false;
    if (literal != nullptr && wanted >= out && wanted - out < length)
      *literal = in + wanted - out;
    if (length != 0) {
      if (dst == nullptr) return false;
      memcpy(dst + out, src + in, length);
    }
    in += length;
    out += length;
    if (in == sn) return out == dn;
    if (sn - in < 2) return false;
    const size_t distance = U16(src + in);
    in += 2;
    length = token & 15;
    if (!extend(length) || length > SIZE_MAX - 4) return false;
    length += 4;
    if (distance == 0 || distance > out || length > dn - out) return false;
    for (size_t k = 0; k < length; ++k) {
      if (distance > out + k) return false;
      if (dst == nullptr) return false;
      dst[out + k] = dst[out + k - distance];
    }
    out += length;
  }
  return out == dn;
}

bool AdaptImage(uint8_t* image, size_t image_size, std::vector<Edit>& edits, size_t& hidden, size_t& arch_gates, std::string& why) {
  auto fail = [&](const char* message) { why = message; return false; };
  if(!image||image_size<sizeof(IMAGE_DOS_HEADER))return fail("image is too small"); auto* dos=reinterpret_cast<IMAGE_DOS_HEADER*>(image); if(dos->e_magic!=IMAGE_DOS_SIGNATURE||dos->e_lfanew<static_cast<LONG>(sizeof(IMAGE_DOS_HEADER))||static_cast<size_t>(dos->e_lfanew)>image_size-sizeof(IMAGE_NT_HEADERS64))return fail("PE DOS header invalid"); auto* nt=reinterpret_cast<IMAGE_NT_HEADERS64*>(image+dos->e_lfanew); if(nt->Signature!=IMAGE_NT_SIGNATURE||nt->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC||nt->OptionalHeader.SizeOfImage!=image_size||nt->OptionalHeader.SizeOfHeaders>image_size)return fail("PE NT headers invalid"); if(nt->FileHeader.NumberOfSections==0||static_cast<size_t>(dos->e_lfanew)+sizeof(DWORD)+sizeof(IMAGE_FILE_HEADER)+nt->FileHeader.SizeOfOptionalHeader+static_cast<size_t>(nt->FileHeader.NumberOfSections)*sizeof(IMAGE_SECTION_HEADER)>image_size)return fail("PE section table invalid");
  auto contains=[&](uint32_t r,size_t n){return r<image_size&&n<=image_size-r;}; auto exp=nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT]; if(!contains(exp.VirtualAddress,40))return fail("export directory invalid"); auto* d=reinterpret_cast<IMAGE_EXPORT_DIRECTORY*>(image+exp.VirtualAddress); if(!contains(d->AddressOfNames,4ull*d->NumberOfNames)||!contains(d->AddressOfNameOrdinals,2ull*d->NumberOfNames)||!contains(d->AddressOfFunctions,4ull*d->NumberOfFunctions))return fail("export arrays invalid");
  auto* names=reinterpret_cast<uint32_t*>(image+d->AddressOfNames);auto* ords=reinterpret_cast<uint16_t*>(image+d->AddressOfNameOrdinals);auto* funcs=reinterpret_cast<uint32_t*>(image+d->AddressOfFunctions);auto find=[&](const char* wanted)->uint32_t{for(uint32_t i=0;i<d->NumberOfNames;i++){if(!contains(names[i],1))continue;const char* s=reinterpret_cast<const char*>(image+names[i]);if(strcmp(s,wanted)==0&&ords[i]<d->NumberOfFunctions)return funcs[ords[i]];}return 0;};
  uint32_t arch_rva=find("NVSDK_NGX_GetGPUArchitecture"), req_rva=find("NVSDK_NGX_D3D12_GetFeatureRequirements"); if(!contains(arch_rva,6)||!contains(req_rva,0x600))return fail("required NGX exports out of range"); if(image[arch_rva]!=0xB8||image[arch_rva+5]!=0xC3||U32(image+arch_rva+1)!=kAdaArchitecture)return fail("architecture export does not match expected Ada stub"); Edit e{};if(!Add(e,image+arch_rva+1,0x90,0x70))return fail("architecture edit precondition mismatch");edits.push_back(e);
  std::vector<uint8_t> work; size_t hit=0; size_t ptx89=0, cubin89=0;
  for (size_t i=0; i+16<=image_size; i+=4) {
    if (U32(image+i)!=0xBA55ED50u) continue;
    uint64_t payload=U64(image+i+8);
    if (!payload || payload>64*1024*1024-16 || payload>image_size-i-16) continue;
    size_t end=i+16+static_cast<size_t>(payload), at=i+16;
    std::vector<std::tuple<size_t,size_t,size_t,uint16_t,uint32_t,uint32_t,uint64_t,uint64_t>> entries;
    bool bad=false;
    while (at<end) {
      if (end-at<64) { bad=true; break; }
      uint16_t kind=U16(image+at); uint32_t h=U32(image+at+4); uint64_t ps=U64(image+at+8);
      if ((kind!=1&&kind!=2)||U16(image+at+2)!=0x101||h<64||h>4096||ps>end-at-h) { bad=true; break; }
      entries.emplace_back(at,h,ps,kind,U32(image+at+28),U32(image+at+16),U64(image+at+40),U64(image+at+56)); at+=h+static_cast<size_t>(ps);
    }
    if (bad || at!=end) continue;
    for (size_t j=0;j<entries.size();j++) {
      auto [eo,h,ps,kind,a,cs,flags,raw]=entries[j];
      if (kind==2&&a==89) ++cubin89; if (kind!=1||a!=89||!(flags&0x2000)||!cs||!raw||cs>ps||raw>32*1024*1024) continue; ++ptx89;
      const uint8_t* comp=image+eo+h; work.assign(raw,0); if(!donor_lz4::Decompress(comp,cs,work.data(),raw,SIZE_MAX,&hit)) { why = "PTX LZ4 decompression failed at fatbin offset " + std::to_string(i) + " entry " + std::to_string(j) + " kind=" + std::to_string(kind) + " flags=0x"; char flags_text[32]{}; sprintf_s(flags_text, "%llX", static_cast<unsigned long long>(flags)); why += flags_text; why += " compressed=" + std::to_string(cs) + " payload=" + std::to_string(ps) + " raw=" + std::to_string(raw); return false; }
      const uint8_t* needle=reinterpret_cast<const uint8_t*>(".target sm_89"); auto it=std::search(work.begin(),work.end(),needle,needle+13);
      if(it==work.end()||(it!=work.begin()&&it[-1]!='\n')||std::search(it+13,work.end(),needle,needle+13)!=work.end()) return fail("PTX sm_89 target validation failed");
      size_t digit=static_cast<size_t>(it-work.begin())+12, lit=SIZE_MAX; if(!donor_lz4::Decompress(comp,cs,work.data(),raw,digit,&lit)||lit==SIZE_MAX||comp[lit]!='9') return fail("PTX target literal is not writable");
      std::vector<uint8_t> edited(comp,comp+cs); edited[lit]='6'; std::vector<uint8_t> check(raw); if(!donor_lz4::Decompress(edited.data(),edited.size(),check.data(),raw,SIZE_MAX,&hit)) return fail("PTX recompression validation failed"); work[digit]='6'; if(check!=work)return fail("PTX transformed bytes did not validate");
      if(!Add(e,image+eo+28,89,86)) return fail("PTX cubin target precondition mismatch"); edits.push_back({image+eo+28,89,86});
      if (j+1<entries.size()) { uint64_t visible=eo+h+ps-16-i; for(unsigned k=0;k<8;k++){uint8_t before=image[i+8+k], after=static_cast<uint8_t>(visible>>(8*k)); if(before!=after) edits.push_back({image+i+8+k,before,after});} hidden += entries.size()-j-1; }
    }
  }
  // Requirements store is patched after all fatbin validation, so a failed
  // discovery never leaves a partially adapted image.
  std::vector<uint8_t*> stores; for(size_t k=0;k+8<=0x600;k++)if(image[req_rva+k]==0xC7&&image[req_rva+k+1]==0x44&&image[req_rva+k+2]==0x24&&U32(image+req_rva+k+4)==kAdaArchitecture)stores.push_back(image+req_rva+k+4);if(stores.size()!=1)return fail("feature requirements architecture store not found uniquely");edits.push_back({stores[0],0x90,0x70});
  const auto* sections = IMAGE_FIRST_SECTION(nt);
  arch_gates = 0;
  size_t executable_sections = 0;
  size_t all_cmp_eax = 0;
  size_t all_cmp_r32 = 0;
  uint32_t first_candidate_rva = 0;
  std::array<size_t, 256> cmp_low_bytes{};
  for (WORD s = 0; s < nt->FileHeader.NumberOfSections; ++s) {
    if ((sections[s].Characteristics & IMAGE_SCN_MEM_EXECUTE) == 0) continue;
    ++executable_sections;
    const size_t start = sections[s].VirtualAddress;
    const size_t size = sections[s].Misc.VirtualSize;
    if (start >= image_size || size < 6 || size > image_size - start) continue;
    for (size_t off = 0; off + 6 <= size; ++off) {
      const uint8_t* p = image + start + off;
      const bool cmp_eax = p[0] == 0x3D && p[2] == 0x01 && p[3] == 0x00 && p[4] == 0x00;
      const bool cmp_r32 = p[0] == 0x81 && p[1] >= 0xF8 && p[1] <= 0xFF && p[3] == 0x01 && p[4] == 0x00 && p[5] == 0x00;
      if (cmp_eax) ++all_cmp_eax;
      if (cmp_r32) ++all_cmp_r32;
      if (cmp_eax) ++cmp_low_bytes[p[1]];
      if (cmp_r32) ++cmp_low_bytes[p[2]];
      const bool arch_cmp_eax = cmp_eax && p[1] == 0xB0;
      const bool arch_cmp_r32 = cmp_r32 && p[2] == 0xB0;
      if ((arch_cmp_eax || arch_cmp_r32) && first_candidate_rva == 0)
        first_candidate_rva = static_cast<uint32_t>(reinterpret_cast<const uint8_t*>(p) - image);
      if (arch_cmp_eax) { edits.push_back({const_cast<uint8_t*>(p) + 1, 0xB0, 0x70}); ++arch_gates; }
      else if (arch_cmp_r32) { edits.push_back({const_cast<uint8_t*>(p) + 2, 0xB0, 0x70}); ++arch_gates; }
    }
  }
  if (arch_gates > 4) {
    why = "provider architecture gate count outside donor range: " + std::to_string(arch_gates) +
      " exec_sections=" + std::to_string(executable_sections) +
      " cmp_eax_any=" + std::to_string(all_cmp_eax) +
      " cmp_r32_any=" + std::to_string(all_cmp_r32) +
      " first_candidate_rva=0x";
    char rva[32]{}; sprintf_s(rva, "%X", first_candidate_rva); why += rva;
    why += " low_bytes=";
    for (size_t b = 0; b < cmp_low_bytes.size(); ++b) {
      if (cmp_low_bytes[b] == 0) continue;
      char item[32]{}; sprintf_s(item, "%02X:%zu,", static_cast<unsigned>(b), cmp_low_bytes[b]); why += item;
    }
    return false;
  }
  if(ptx89!=97||cubin89!=79){ why = "unexpected provider fatbin counts ptx89=" + std::to_string(ptx89) + " cubin89=" + std::to_string(cubin89); return false; } std::sort(edits.begin(),edits.end(),[](const Edit&a,const Edit&b){return a.address<b.address;}); for(size_t i=1;i<edits.size();++i)if(edits[i-1].address==edits[i].address)return fail("duplicate provider edit address"); for(const auto&x:edits)if(!x.address||*x.address!=x.before)return fail("provider edit precondition mismatch");
  return true;
}
} // namespace

void Session::ConsumeApplyResult(TransactionResult result, const std::vector<Edit>& edits) {
  qualified_ = false;
  edits_ = edits;
  switch (result) {
    case TransactionResult::Applied:
      qualified_ = true;
      rollback_verified_ = true;
      break;
    case TransactionResult::ApplyFailedRollbackSucceeded:
      edits_.clear();
      hidden_cubins_ = 0;
      rollback_verified_ = true;
      break;
    case TransactionResult::ApplyFailedRollbackFailed:
      rollback_verified_ = false;
      break;
    case TransactionResult::ApplyFailed:
      // No edit was applied, so the initial verified-clean state remains valid,
      // but the candidate edit list remains recorded for the failed session.
      rollback_verified_ = true;
      break;
    case TransactionResult::RollbackSucceeded:
    case TransactionResult::RollbackFailed:
      break;
  }
}

bool Session::LoadAndAdapt(const std::wstring& path,std::string& detail){
  qualified_=false; rollback_verified_=true; edits_.clear(); hidden_cubins_=0; provider_arch_gate_count_=0;
  std::wstring wanted; if(!Canonical(path,wanted)){detail="provider path is not canonical absolute path";return false;}
  DWORD attrs=GetFileAttributesW(wanted.c_str());if(attrs==INVALID_FILE_ATTRIBUTES||(attrs&FILE_ATTRIBUTE_DIRECTORY)){detail="provider file does not exist";return false;}
  if(!FileVersionExact(wanted)){detail="provider version is not exactly 310.2.1.0";return false;}
  std::string hash;if(!Sha256(wanted,hash)||_stricmp(hash.c_str(),kExpectedSha256)!=0){detail="provider SHA-256 mismatch";return false;}
  if(HMODULE existing=GetModuleHandleW(L"nvngx_dlssg.dll")){std::vector<wchar_t> mapped(32768);DWORD n=GetModuleFileNameW(existing,mapped.data(),static_cast<DWORD>(mapped.size()));if(!n||n>=mapped.size()){detail="existing provider mapping path unavailable";return false;}std::wstring mapped_canon;if(!Canonical(mapped.data(),mapped_canon)||_wcsicmp(mapped_canon.c_str(),wanted.c_str())!=0){detail="different same-base-name provider is already mapped";return false;}detail="provider is already mapped; refusing duplicate load";return false;}
  module_=LoadLibraryExW(wanted.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);if(!module_){detail="LoadLibraryExW failed";return false;}canonical_path_=wanted;
  uint8_t*image=reinterpret_cast<uint8_t*>(module_);
  if(!MappedReadable(image,sizeof(IMAGE_DOS_HEADER),image)){detail="mapped provider DOS header is not readable";return false;}
  IMAGE_DOS_HEADER dos{}; memcpy(&dos,image,sizeof(dos));
  if(dos.e_magic!=IMAGE_DOS_SIGNATURE||dos.e_lfanew<static_cast<LONG>(sizeof(IMAGE_DOS_HEADER))||static_cast<uintptr_t>(dos.e_lfanew)>0x40000000u){detail="invalid mapped PE DOS header";return false;}
  const size_t nt_prefix=sizeof(DWORD)+sizeof(IMAGE_FILE_HEADER)+sizeof(WORD);
  auto *nt_address=image+static_cast<size_t>(dos.e_lfanew);
  if(!MappedReadable(nt_address,nt_prefix,image)){detail="mapped provider NT header prefix is not readable";return false;}
  DWORD signature=0; IMAGE_FILE_HEADER file{}; memcpy(&signature,nt_address,sizeof(signature)); memcpy(&file,nt_address+sizeof(signature),sizeof(file));
  if(signature!=IMAGE_NT_SIGNATURE||file.SizeOfOptionalHeader<sizeof(IMAGE_OPTIONAL_HEADER64)||!MappedReadable(nt_address,sizeof(DWORD)+sizeof(IMAGE_FILE_HEADER)+file.SizeOfOptionalHeader,image)){detail="invalid mapped PE64 NT headers";return false;}
  IMAGE_NT_HEADERS64 nt{}; memcpy(&nt,nt_address,sizeof(nt));
  size_t image_size=nt.OptionalHeader.SizeOfImage;
  MODULEINFO module_info{};
  if(nt.OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC||!image_size||image_size>0x40000000||
     !GetModuleInformation(GetCurrentProcess(), module_, &module_info, sizeof(module_info)) ||
     module_info.lpBaseOfDll != module_ || module_info.SizeOfImage != image_size){detail="mapped provider SizeOfImage does not match module mapping";return false;}
  std::vector<wchar_t> actual(32768);DWORD n=GetModuleFileNameW(module_,actual.data(),static_cast<DWORD>(actual.size()));if(!n||n>=actual.size()){detail="mapped provider path unavailable or truncated";return false;}std::wstring actual_canon;if(!Canonical(actual.data(),actual_canon)||_wcsicmp(actual_canon.c_str(),wanted.c_str())!=0){detail="mapped provider path mismatch";return false;}
  std::vector<Edit> planned_image;
  if(!AdaptImage(image,image_size,planned_image,hidden_cubins_,provider_arch_gate_count_,detail)){Rollback();return false;}
  edits_.clear(); edits_.reserve(planned_image.size());
  for(const auto& planned : planned_image){ if(!planned.address||planned.address<image||static_cast<size_t>(planned.address-image)>=image_size||*planned.address!=planned.before){Rollback();detail="provider edit address validation failed";return false;} edits_.push_back(planned);}
  std::vector<size_t> applied;
  const auto result=ApplyEdits(edits_,WindowsTransactionOps(),applied,detail);
  ConsumeApplyResult(result,edits_);
  if(result!=TransactionResult::Applied){Rollback();return false;}
  if(!VerifyReadback(detail)){Rollback();return false;}
  return true;
}
bool Session::InspectOnly(const std::wstring& path, std::string& detail,
                          size_t& edit_count, size_t& hidden_cubins) {
  qualified_=false; rollback_verified_=true; edits_.clear(); hidden_cubins_=0; provider_arch_gate_count_=0;
  std::wstring wanted; if(!Canonical(path,wanted)){detail="provider path is not canonical absolute path";return false;}
  DWORD attrs=GetFileAttributesW(wanted.c_str());if(attrs==INVALID_FILE_ATTRIBUTES||(attrs&FILE_ATTRIBUTE_DIRECTORY)){detail="provider file does not exist";return false;}
  if(!FileVersionExact(wanted)){detail="provider version is not exactly 310.2.1.0";return false;}
  std::string hash;if(!Sha256(wanted,hash)||_stricmp(hash.c_str(),kExpectedSha256)!=0){detail="provider SHA-256 mismatch";return false;}
  if(HMODULE existing=GetModuleHandleW(L"nvngx_dlssg.dll")){std::vector<wchar_t> mapped(32768);DWORD n=GetModuleFileNameW(existing,mapped.data(),static_cast<DWORD>(mapped.size()));if(!n||n>=mapped.size()){detail="existing provider mapping path unavailable";return false;}std::wstring mapped_canon;if(!Canonical(mapped.data(),mapped_canon)||_wcsicmp(mapped_canon.c_str(),wanted.c_str())!=0){detail="different same-base-name provider is already mapped";return false;}detail="provider is already mapped; refusing duplicate load";return false;}
  module_=LoadLibraryExW(wanted.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);if(!module_){detail="LoadLibraryExW failed";return false;} canonical_path_=wanted;
  uint8_t*image=reinterpret_cast<uint8_t*>(module_);
  if(!MappedReadable(image,sizeof(IMAGE_DOS_HEADER),image)){detail="mapped provider DOS header is not readable";return false;}
  IMAGE_DOS_HEADER dos{}; memcpy(&dos,image,sizeof(dos));
  if(dos.e_magic!=IMAGE_DOS_SIGNATURE||dos.e_lfanew<static_cast<LONG>(sizeof(IMAGE_DOS_HEADER))||static_cast<uintptr_t>(dos.e_lfanew)>0x40000000u){detail="invalid mapped PE DOS header";return false;}
  const size_t nt_prefix=sizeof(DWORD)+sizeof(IMAGE_FILE_HEADER)+sizeof(WORD); auto *nt_address=image+static_cast<size_t>(dos.e_lfanew);
  if(!MappedReadable(nt_address,nt_prefix,image)){detail="mapped provider NT header prefix is not readable";return false;}
  DWORD signature=0; IMAGE_FILE_HEADER file{}; memcpy(&signature,nt_address,sizeof(signature)); memcpy(&file,nt_address+sizeof(signature),sizeof(file));
  if(signature!=IMAGE_NT_SIGNATURE||file.SizeOfOptionalHeader<sizeof(IMAGE_OPTIONAL_HEADER64)||!MappedReadable(nt_address,sizeof(DWORD)+sizeof(IMAGE_FILE_HEADER)+file.SizeOfOptionalHeader,image)){detail="invalid mapped PE64 NT headers";return false;}
  IMAGE_NT_HEADERS64 nt{}; memcpy(&nt,nt_address,sizeof(nt)); size_t image_size=nt.OptionalHeader.SizeOfImage;
  MODULEINFO module_info{};
  if(nt.OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC||!image_size||image_size>0x40000000||
     !GetModuleInformation(GetCurrentProcess(), module_, &module_info, sizeof(module_info)) ||
     module_info.lpBaseOfDll != module_ || module_info.SizeOfImage != image_size){detail="mapped provider SizeOfImage does not match module mapping";return false;}
  std::vector<wchar_t> actual(32768);DWORD n=GetModuleFileNameW(module_,actual.data(),static_cast<DWORD>(actual.size()));if(!n||n>=actual.size()){detail="mapped provider path unavailable or truncated";return false;}std::wstring actual_canon;if(!Canonical(actual.data(),actual_canon)||_wcsicmp(actual_canon.c_str(),wanted.c_str())!=0){detail="mapped provider path mismatch";return false;}
  std::vector<Edit> planned; size_t hidden=0;
  if(!AdaptImage(image,image_size,planned,hidden,provider_arch_gate_count_,detail))return false;
  edit_count=planned.size(); hidden_cubins=hidden; return true;
}
bool Session::VerifyReadback(std::string& detail)const{for(const auto&e:edits_)if(*e.address!=e.after){detail="provider edit readback mismatch";return false;}return true;}
bool Session::Rollback(){
  qualified_=false; std::vector<size_t> applied; applied.reserve(edits_.size()); for(size_t i=0;i<edits_.size();++i)applied.push_back(i); std::string detail; const auto result=RollbackEdits(edits_,applied,WindowsTransactionOps(),detail); rollback_verified_=result==TransactionResult::RollbackSucceeded; if(rollback_verified_){edits_.clear();hidden_cubins_=0;provider_arch_gate_count_=0;} return rollback_verified_;
}
bool Session::Unload(){
  if(!module_) return true;
  if(!CanUnloadProvider()) return false;
  const BOOL ok=FreeLibrary(module_);
  if(ok) module_=nullptr;
  return ok!=FALSE;
}
#ifdef AMPERE_PROVIDER_TESTING
TransactionResult Session::ApplySyntheticEditsForTest(const TransactionOps& ops, const std::vector<Edit>& edits, std::string& detail){
  std::vector<size_t> applied;
  const auto result=ApplyEdits(edits,ops,applied,detail);
  ConsumeApplyResult(result,edits);
  return result;
}
#endif
} // namespace ampere_provider
