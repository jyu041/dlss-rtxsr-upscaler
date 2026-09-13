#include "provider_transaction.h"
#include <windows.h>
#include <algorithm>

namespace ampere_provider { namespace {
bool MakeWritable(void *, uint8_t *p, DWORD *old){return VirtualProtect(p,1,PAGE_EXECUTE_READWRITE,old)!=FALSE;}
bool Restore(void *, uint8_t *p, DWORD old){DWORD previous=0; if(!VirtualProtect(p,1,old,&previous))return false; MEMORY_BASIC_INFORMATION m{}; if(previous==0||VirtualQuery(p,&m,sizeof(m))!=sizeof(m)||m.State!=MEM_COMMIT)return false; const DWORD base_now=m.Protect&0xFFu; return base_now!=PAGE_NOACCESS&&base_now!=0&&(m.Protect&(PAGE_GUARD|PAGE_NOACCESS))==0;}
bool Read(void *, uint8_t *p, uint8_t *v){*v=*p;return true;}
bool Write(void *, uint8_t *p, uint8_t v){*p=v;return true;}
bool Flush(void *, uint8_t *p, size_t length){return FlushInstructionCache(GetCurrentProcess(),p,length)!=FALSE;}
}
TransactionOps WindowsTransactionOps(){return {nullptr,MakeWritable,Restore,Read,Write,Flush};}
bool ValidateEdits(const std::vector<Edit>&edits,std::string&detail){for(size_t i=0;i<edits.size();++i)for(size_t j=i+1;j<edits.size();++j)if(edits[i].address==edits[j].address){detail="duplicate edit RVA";return false;}for(const auto&e:edits)if(!e.address){detail="null edit address";return false;}return true;}
namespace {
struct ProtectionGuard {
  const TransactionOps& ops; uint8_t* address; DWORD old; bool& restored;
  ~ProtectionGuard(){restored=ops.restore(ops.context,address,old);}
};
}
TransactionResult RollbackEdits(const std::vector<Edit> &edits,const std::vector<size_t> &applied,const TransactionOps &ops,std::string &detail){
  bool ok=true; for(auto it=applied.rbegin();it!=applied.rend();++it){const auto&e=edits[*it];DWORD old=0;uint8_t value=0;
    if(!ops.make_writable(ops.context,e.address,&old)){ok=false;continue;}
    bool page_ok=true; bool protection_restored=false;
    { ProtectionGuard protection{ops,e.address,old,protection_restored};
      if(!ops.read(ops.context,e.address,&value)) page_ok=false;
      else if(value==e.after){if(!ops.write(ops.context,e.address,e.before))page_ok=false;}
      else if(value!=e.before) page_ok=false;
      if(page_ok&&!ops.flush(ops.context,e.address,1))page_ok=false;
      if(page_ok&&(!ops.read(ops.context,e.address,&value)||value!=e.before))page_ok=false;
    }
    if(!protection_restored) page_ok=false;
    if(!page_ok)ok=false;
  }
  for(auto i:applied){uint8_t value=0;if(!ops.read(ops.context,edits[i].address,&value)||value!=edits[i].before)ok=false;} detail=ok?"ROLLBACK_SUCCESS":"ROLLBACK_FAILED";return ok?TransactionResult::RollbackSucceeded:TransactionResult::RollbackFailed;
}
namespace {
TransactionResult FailApplyWithRollback(const std::vector<Edit>& edits,const std::vector<size_t>& applied,const TransactionOps& ops,std::string& detail){
  const std::string cause = detail;
  if(applied.empty()) return TransactionResult::ApplyFailed;
  const bool rollback_ok = RollbackEdits(edits,applied,ops,detail)==TransactionResult::RollbackSucceeded;
  detail = cause + "; rollback=" + (rollback_ok ? "succeeded" : "failed");
  return rollback_ok
    ? TransactionResult::ApplyFailedRollbackSucceeded
    : TransactionResult::ApplyFailedRollbackFailed;
}
}
TransactionResult ApplyEdits(const std::vector<Edit>&edits,const TransactionOps&ops,std::vector<size_t>&applied,std::string&detail){
  applied.clear(); if(!ValidateEdits(edits,detail))return TransactionResult::ApplyFailed; for(size_t i=0;i<edits.size();++i){const auto&e=edits[i];uint8_t value=0;DWORD old=0;if(!ops.read(ops.context,e.address,&value)||value!=e.before){detail="before-byte validation failed";return FailApplyWithRollback(edits,applied,ops,detail);}if(!ops.make_writable(ops.context,e.address,&old)){detail="VirtualProtect-to-writable failed";return FailApplyWithRollback(edits,applied,ops,detail);}bool write_ok=false,flush_ok=false,read_ok=false,page_ok=false,protection_restored=false;{ProtectionGuard protection{ops,e.address,old,protection_restored};write_ok=ops.write(ops.context,e.address,e.after);if(write_ok){applied.push_back(i);flush_ok=ops.flush(ops.context,e.address,1);if(flush_ok)read_ok=ops.read(ops.context,e.address,&value)&&value==e.after;}}page_ok=write_ok&&flush_ok&&read_ok&&protection_restored;if(!page_ok){char buffer[256]{};sprintf_s(buffer,"post-write failure index=%zu address=%p write=%d flush=%d read=%d restore=%d",i,e.address,write_ok,flush_ok,read_ok,protection_restored);detail=buffer;return FailApplyWithRollback(edits,applied,ops,detail);}}
  detail="APPLY_SUCCESS";return TransactionResult::Applied;
}
}
