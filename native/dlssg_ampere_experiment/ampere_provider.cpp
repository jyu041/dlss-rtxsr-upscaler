#include "ampere_provider.h"
#include "provider_transaction.h"

#include <bcrypt.h>
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
bool MappedReadable(const uint8_t *base, size_t size) {
  size_t offset = 0;
  while (offset < size) {
    MEMORY_BASIC_INFORMATION m{};
    if (VirtualQuery(base + offset, &m, sizeof(m)) != sizeof(m) || m.State != MEM_COMMIT) return false;
    const DWORD readable = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
      PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    if ((m.Protect & readable) == 0) return false;
    const auto begin = reinterpret_cast<uintptr_t>(m.BaseAddress);
    const auto current = reinterpret_cast<uintptr_t>(base + offset);
    if (current < begin || m.RegionSize > size - offset) return false;
    offset += std::min<size_t>(m.RegionSize - (current - begin), size - offset);
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
bool Lz4(const uint8_t* src,size_t sn,uint8_t* dst,size_t dn,size_t wanted,size_t* literal) {
  size_t i=0,o=0; *literal=SIZE_MAX; while(i<sn){ uint8_t t=src[i++]; size_t l=t>>4; if(l==15){uint8_t b;do{if(i>=sn)return false;b=src[i++];l+=b;}while(b==255);} if(l>sn-i||l>dn-o)return false; if(wanted>=o&&wanted-o<l)*literal=i+wanted-o; if(dst) memcpy(dst+o,src+i,l);i+=l;o+=l;if(i==sn)break;if(sn-i<2)return false;size_t d=src[i]|(src[i+1]<<8);i+=2;size_t m=t&15;if(m==15){uint8_t b;do{if(i>=sn)return false;b=src[i++];m+=b;}while(b==255);}m+=4;if(!d||d>o||m>dn-o)return false;for(size_t k=0;k<m;k++)if(dst)dst[o+k]=dst[o+k-d];o+=m;}return o==dn;
}

bool AdaptImage(uint8_t* image, size_t image_size, std::vector<Edit>& edits, size_t& hidden, std::string& why) {
  (void)why;
  if(!image||image_size<sizeof(IMAGE_DOS_HEADER))return false; auto* dos=reinterpret_cast<IMAGE_DOS_HEADER*>(image); if(dos->e_magic!=IMAGE_DOS_SIGNATURE||dos->e_lfanew<static_cast<LONG>(sizeof(IMAGE_DOS_HEADER))||static_cast<size_t>(dos->e_lfanew)>image_size-sizeof(IMAGE_NT_HEADERS64))return false; auto* nt=reinterpret_cast<IMAGE_NT_HEADERS64*>(image+dos->e_lfanew); if(nt->Signature!=IMAGE_NT_SIGNATURE||nt->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC||nt->OptionalHeader.SizeOfImage!=image_size||nt->OptionalHeader.SizeOfHeaders>image_size)return false; if(nt->FileHeader.NumberOfSections==0||static_cast<size_t>(dos->e_lfanew)+sizeof(DWORD)+sizeof(IMAGE_FILE_HEADER)+nt->FileHeader.SizeOfOptionalHeader+static_cast<size_t>(nt->FileHeader.NumberOfSections)*sizeof(IMAGE_SECTION_HEADER)>image_size)return false;
  auto contains=[&](uint32_t r,size_t n){return r<image_size&&n<=image_size-r;}; auto exp=nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT]; if(!contains(exp.VirtualAddress,40))return false; auto* d=reinterpret_cast<IMAGE_EXPORT_DIRECTORY*>(image+exp.VirtualAddress); if(!contains(d->AddressOfNames,4ull*d->NumberOfNames)||!contains(d->AddressOfNameOrdinals,2ull*d->NumberOfNames)||!contains(d->AddressOfFunctions,4ull*d->NumberOfFunctions))return false;
  auto* names=reinterpret_cast<uint32_t*>(image+d->AddressOfNames);auto* ords=reinterpret_cast<uint16_t*>(image+d->AddressOfNameOrdinals);auto* funcs=reinterpret_cast<uint32_t*>(image+d->AddressOfFunctions);auto find=[&](const char* wanted)->uint32_t{for(uint32_t i=0;i<d->NumberOfNames;i++){if(!contains(names[i],1))continue;const char* s=reinterpret_cast<const char*>(image+names[i]);if(strcmp(s,wanted)==0&&ords[i]<d->NumberOfFunctions)return funcs[ords[i]];}return 0;};
  uint32_t arch_rva=find("NVSDK_NGX_GetGPUArchitecture"), req_rva=find("NVSDK_NGX_D3D12_GetFeatureRequirements"); if(!contains(arch_rva,6)||!contains(req_rva,0x600)||image[arch_rva]!=0xB8||image[arch_rva+5]!=0xC3||U32(image+arch_rva+1)!=kAdaArchitecture)return false; Edit e{};if(!Add(e,image+arch_rva+1,0x90,0x70))return false;edits.push_back(e);
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
      const uint8_t* comp=image+i+eo+h; work.assign(raw,0); if(!Lz4(comp,cs,work.data(),raw,SIZE_MAX,&hit)) return false;
      const uint8_t* needle=reinterpret_cast<const uint8_t*>(".target sm_89"); auto it=std::search(work.begin(),work.end(),needle,needle+13);
      if(it==work.end()||(it!=work.begin()&&it[-1]!='\n')||std::search(it+13,work.end(),needle,needle+13)!=work.end()) return false;
      size_t digit=static_cast<size_t>(it-work.begin())+12, lit=SIZE_MAX; if(!Lz4(comp,cs,nullptr,raw,digit,&lit)||lit==SIZE_MAX||comp[lit]!='9') return false;
      std::vector<uint8_t> edited(comp,comp+cs); edited[lit]='6'; std::vector<uint8_t> check(raw); if(!Lz4(edited.data(),edited.size(),check.data(),raw,SIZE_MAX,&hit)) return false; work[digit]='6'; if(check!=work)return false;
      if(!Add(e,image+i+eo+28,89,86)) return false; edits.push_back({image+i+eo+28,89,86});
      if (j+1<entries.size()) { uint64_t visible=eo+h+ps-16; for(unsigned k=0;k<8;k++){uint8_t before=image[i+8+k], after=static_cast<uint8_t>(visible>>(8*k)); if(before!=after) edits.push_back({image+i+8+k,before,after});} hidden += entries.size()-j-1; }
    }
  }
  // Requirements store is patched after all fatbin validation, so a failed
  // discovery never leaves a partially adapted image.
  std::vector<uint8_t*> stores; for(size_t k=0;k+8<=0x600;k++)if(image[req_rva+k]==0xC7&&image[req_rva+k+1]==0x44&&image[req_rva+k+2]==0x24&&U32(image+req_rva+k+4)==kAdaArchitecture)stores.push_back(image+req_rva+k+4);if(stores.size()!=1)return false;edits.push_back({stores[0],0x90,0x70});
  if(ptx89!=97||cubin89!=79)return false; std::sort(edits.begin(),edits.end(),[](const Edit&a,const Edit&b){return a.address<b.address;}); for(size_t i=1;i<edits.size();++i)if(edits[i-1].address==edits[i].address)return false; for(const auto&x:edits)if(!x.address||*x.address!=x.before)return false;
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
  qualified_=false; rollback_verified_=true; edits_.clear(); hidden_cubins_=0;
  std::wstring wanted; if(!Canonical(path,wanted)){detail="provider path is not canonical absolute path";return false;}
  DWORD attrs=GetFileAttributesW(wanted.c_str());if(attrs==INVALID_FILE_ATTRIBUTES||(attrs&FILE_ATTRIBUTE_DIRECTORY)){detail="provider file does not exist";return false;}
  if(!FileVersionExact(wanted)){detail="provider version is not exactly 310.2.1.0";return false;}
  std::string hash;if(!Sha256(wanted,hash)||_stricmp(hash.c_str(),kExpectedSha256)!=0){detail="provider SHA-256 mismatch";return false;}
  if(HMODULE existing=GetModuleHandleW(L"nvngx_dlssg.dll")){std::vector<wchar_t> mapped(32768);DWORD n=GetModuleFileNameW(existing,mapped.data(),static_cast<DWORD>(mapped.size()));if(!n||n>=mapped.size()){detail="existing provider mapping path unavailable";return false;}std::wstring mapped_canon;if(!Canonical(mapped.data(),mapped_canon)||_wcsicmp(mapped_canon.c_str(),wanted.c_str())!=0){detail="different same-base-name provider is already mapped";return false;}detail="provider is already mapped; refusing duplicate load";return false;}
  module_=LoadLibraryExW(wanted.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);if(!module_){detail="LoadLibraryExW failed";return false;}canonical_path_=wanted;
  uint8_t*image=reinterpret_cast<uint8_t*>(module_);
  if(!MappedReadable(image,sizeof(IMAGE_DOS_HEADER))){detail="mapped provider DOS header is not readable";return false;}
  IMAGE_DOS_HEADER dos{}; memcpy(&dos,image,sizeof(dos));
  if(dos.e_magic!=IMAGE_DOS_SIGNATURE||dos.e_lfanew<static_cast<LONG>(sizeof(IMAGE_DOS_HEADER))||static_cast<uintptr_t>(dos.e_lfanew)>0x40000000u){detail="invalid mapped PE DOS header";return false;}
  const size_t nt_prefix=sizeof(DWORD)+sizeof(IMAGE_FILE_HEADER)+sizeof(WORD);
  auto *nt_address=image+static_cast<size_t>(dos.e_lfanew);
  if(!MappedReadable(nt_address,nt_prefix)){detail="mapped provider NT header prefix is not readable";return false;}
  DWORD signature=0; IMAGE_FILE_HEADER file{}; memcpy(&signature,nt_address,sizeof(signature)); memcpy(&file,nt_address+sizeof(signature),sizeof(file));
  if(signature!=IMAGE_NT_SIGNATURE||file.SizeOfOptionalHeader<sizeof(IMAGE_OPTIONAL_HEADER64)||!MappedReadable(nt_address,sizeof(DWORD)+sizeof(IMAGE_FILE_HEADER)+file.SizeOfOptionalHeader)){detail="invalid mapped PE64 NT headers";return false;}
  IMAGE_NT_HEADERS64 nt{}; memcpy(&nt,nt_address,sizeof(nt));
  size_t image_size=nt.OptionalHeader.SizeOfImage;
  if(nt.OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC||!image_size||image_size>0x40000000||!MappedReadable(image,image_size)){detail="mapped provider SizeOfImage is outside readable mapping";return false;}
  std::vector<wchar_t> actual(32768);DWORD n=GetModuleFileNameW(module_,actual.data(),static_cast<DWORD>(actual.size()));if(!n||n>=actual.size()){detail="mapped provider path unavailable or truncated";return false;}std::wstring actual_canon;if(!Canonical(actual.data(),actual_canon)||_wcsicmp(actual_canon.c_str(),wanted.c_str())!=0){detail="mapped provider path mismatch";return false;}
  if(!AdaptImage(image,image_size,edits_,hidden_cubins_,detail)){Rollback();detail="provider layout/adaptation validation failed";return false;}
  std::vector<size_t> applied;
  const auto result=ApplyEdits(edits_,WindowsTransactionOps(),applied,detail);
  ConsumeApplyResult(result,edits_);
  if(result!=TransactionResult::Applied){Rollback();detail="provider layout/adaptation validation failed";return false;}
  if(!VerifyReadback(detail)){Rollback();return false;}
  return true;
}
bool Session::VerifyReadback(std::string& detail)const{for(const auto&e:edits_)if(*e.address!=e.after){detail="provider edit readback mismatch";return false;}return true;}
bool Session::Rollback(){
  qualified_=false; std::vector<size_t> applied; applied.reserve(edits_.size()); for(size_t i=0;i<edits_.size();++i)applied.push_back(i); std::string detail; const auto result=RollbackEdits(edits_,applied,WindowsTransactionOps(),detail); rollback_verified_=result==TransactionResult::RollbackSucceeded; if(rollback_verified_){edits_.clear();hidden_cubins_=0;} return rollback_verified_;
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
