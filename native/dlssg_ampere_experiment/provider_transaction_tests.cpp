#include "provider_transaction.h"
#include <cassert>
#include <cstdio>
#include <vector>

using namespace ampere_provider;

struct Fake {
  int protect_fail=-1, restore_fail=-1, read_fail=-1, readback_mismatch=-1;
  int write_fail=-1, flush_fail=-1;
  int protect_calls=0, restore_calls=0, read_calls=0, write_calls=0, flush_calls=0;
  int writes_to_after=0;
};

bool P(void* c,uint8_t*,DWORD* old){auto* f=static_cast<Fake*>(c);*old=0x20;return f->protect_calls++!=f->protect_fail;}
bool R(void* c,uint8_t*,DWORD){auto* f=static_cast<Fake*>(c);return f->restore_calls++!=f->restore_fail;}
bool G(void* c,uint8_t* p,uint8_t* v){auto* f=static_cast<Fake*>(c);const int call=f->read_calls++;if(call==f->read_fail)return false;*v=*p;if(call==f->readback_mismatch)*v^=1;return true;}
bool W(void* c,uint8_t* p,uint8_t v){auto* f=static_cast<Fake*>(c);if(f->write_calls++==f->write_fail)return false;if(v==0x20)++f->writes_to_after;*p=v;return true;}
bool F(void* c,uint8_t*,size_t){auto* f=static_cast<Fake*>(c);return f->flush_calls++!=f->flush_fail;}
TransactionOps Ops(Fake& f){return {&f,P,R,G,W,F};}

void Pass(const char* label){std::printf("%s: PASS\n",label);}
const char* ResultName(TransactionResult result){
  switch(result){
    case TransactionResult::Applied:return "Applied";
    case TransactionResult::ApplyFailed:return "ApplyFailed";
    case TransactionResult::ApplyFailedRollbackSucceeded:return "ApplyFailedRollbackSucceeded";
    case TransactionResult::ApplyFailedRollbackFailed:return "ApplyFailedRollbackFailed";
    case TransactionResult::RollbackSucceeded:return "RollbackSucceeded";
    case TransactionResult::RollbackFailed:return "RollbackFailed";
  }
  return "Unknown";
}
void Reset(uint8_t* memory){for(int i=0;i<16;++i)memory[i]=0x10;}

int main(){
  uint8_t memory[16]{}; Reset(memory);
  std::vector<Edit> edits={{memory,0x10,0x20},{memory+8,0x10,0x30}};
  std::vector<size_t> applied; std::string detail; Fake f;

  Reset(memory); f={};
  assert(ApplyEdits(edits,Ops(f),applied,detail)==TransactionResult::Applied);
  assert(memory[0]==0x20&&memory[8]==0x30&&applied.size()==2); Pass("TEST_A_NORMAL_APPLY");

  Reset(memory); memory[0]=0x99; f={};
  auto b=ApplyEdits(edits,Ops(f),applied,detail);
  assert(b!=TransactionResult::Applied&&applied.empty()&&f.write_calls==0&&memory[0]==0x99); Pass("TEST_B_BEFORE_MISMATCH_ZERO_WRITES");

  Reset(memory); f={}; f.write_fail=0;
  auto c=ApplyEdits(edits,Ops(f),applied,detail);
  assert(c!=TransactionResult::Applied&&memory[0]==0x10&&memory[8]==0x10); Pass("TEST_C_CURRENT_WRITE_FAILURE");

  Reset(memory); f={}; f.write_fail=1;
  auto d=ApplyEdits(edits,Ops(f),applied,detail);
  assert(d==TransactionResult::ApplyFailedRollbackSucceeded&&applied.size()==1&&memory[0]==0x10&&memory[8]==0x10); Pass("TEST_D_LATER_EDIT_FAILURE");

  Reset(memory); f={}; f.protect_fail=0;
  auto e=ApplyEdits(edits,Ops(f),applied,detail);
  assert(e==TransactionResult::ApplyFailed&&memory[0]==0x10&&memory[8]==0x10); Pass("TEST_E_MAKE_WRITABLE_FAILURE");

  Reset(memory); f={}; f.restore_fail=0;
  auto ff=ApplyEdits(edits,Ops(f),applied,detail);
  assert(ff==TransactionResult::ApplyFailedRollbackSucceeded&&f.restore_calls>=2); Pass("TEST_F_PROTECTION_RESTORE_FAILURE");

  Reset(memory); f={}; f.readback_mismatch=3;
  auto g=ApplyEdits(edits,Ops(f),applied,detail);
  assert(g==TransactionResult::ApplyFailedRollbackSucceeded&&applied.size()==2&&memory[0]==0x10&&memory[8]==0x10); Pass("TEST_G_POST_WRITE_READBACK_MISMATCH_ROLLBACK");

  Reset(memory); f={}; assert(ApplyEdits(edits,Ops(f),applied,detail)==TransactionResult::Applied);
  assert(RollbackEdits(edits,applied,Ops(f),detail)==TransactionResult::RollbackSucceeded&&memory[0]==0x10&&memory[8]==0x10); Pass("TEST_H_EXPLICIT_ROLLBACK");

  Reset(memory); f={}; std::vector<Edit> duplicate={{memory,0x10,0x20},{memory,0x10,0x30}};
  assert(!ValidateEdits(duplicate,detail)&&ApplyEdits(duplicate,Ops(f),applied,detail)!=TransactionResult::Applied&&memory[0]==0x10); Pass("TEST_I_DUPLICATE_RVA");

  Reset(memory); f={}; assert(ApplyEdits(edits,Ops(f),applied,detail)==TransactionResult::Applied);
  f.restore_fail=f.restore_calls; assert(RollbackEdits(edits,applied,Ops(f),detail)==TransactionResult::RollbackFailed); Pass("TEST_J_ROLLBACK_FAILURE");

  Reset(memory); f={}; f.flush_fail=0;
  auto k=ApplyEdits(edits,Ops(f),applied,detail);
  assert(k==TransactionResult::ApplyFailedRollbackSucceeded&&applied.size()==1&&memory[0]==0x10&&memory[8]==0x10); Pass("TEST_K_APPLY_CACHE_FLUSH_FAILURE");

  Reset(memory); f={}; assert(ApplyEdits(edits,Ops(f),applied,detail)==TransactionResult::Applied);
  f.flush_fail=f.flush_calls; assert(RollbackEdits(edits,applied,Ops(f),detail)==TransactionResult::RollbackFailed); Pass("TEST_L_ROLLBACK_CACHE_FLUSH_FAILURE");

  Reset(memory); f={}; assert(ApplyEdits(edits,Ops(f),applied,detail)==TransactionResult::Applied);
  std::vector<size_t> one{0}; f.read_fail=f.read_calls; const int restores_before=f.restore_calls;
  assert(RollbackEdits(edits,one,Ops(f),detail)==TransactionResult::RollbackFailed&&f.restore_calls==restores_before+1); Pass("TEST_M_ROLLBACK_READ_FAILURE_RESTORES_PROTECTION");

  Reset(memory); f={}; TransactionOps positive_ops=Ops(f); Session positive;
  assert(positive.ApplySyntheticEditsForTest(positive_ops,edits,detail)==TransactionResult::Applied);
  assert(positive.qualified()&&positive.Rollback()&&positive.CanUnloadProvider());
  Pass("UNLOAD_POSITIVE_CONTROL");

  Reset(memory); f={}; f.readback_mismatch=2;
  auto n_success=ApplyEdits(edits,Ops(f),applied,detail);
  assert(n_success==TransactionResult::ApplyFailedRollbackSucceeded&&f.write_calls>=2&&memory[0]==0x10); Pass("TEST_N_LATE_BEFORE_MISMATCH_ROLLBACK_SUCCESS");

  Reset(memory); f={}; f.readback_mismatch=2; f.restore_fail=1; TransactionOps n_ops=Ops(f); Session n_session_failure;
  auto n=n_session_failure.ApplySyntheticEditsForTest(n_ops,edits,detail);
  const bool n_qualified=n_session_failure.qualified(); const bool n_can_unload=n_session_failure.CanUnloadProvider();
  assert(n==TransactionResult::ApplyFailedRollbackFailed&&f.writes_to_after>=1&&f.write_calls>=2&&f.read_calls>=4&&f.restore_calls>=2&&detail=="ROLLBACK_FAILED");
  assert(!n_qualified&&!n_can_unload);
  std::printf("TEST_N_LATE_BEFORE_MISMATCH_ROLLBACK_FAILURE: PASS\nN: result=%s qualified=%s CanUnloadProvider=%s\n",ResultName(n),n_qualified?"true":"false",n_can_unload?"true":"false");

  Reset(memory); f={}; f.protect_fail=1;
  auto o_success=ApplyEdits(edits,Ops(f),applied,detail);
  assert(o_success==TransactionResult::ApplyFailedRollbackSucceeded&&f.write_calls>=2&&memory[0]==0x10); Pass("TEST_O_LATE_MAKE_WRITABLE_FAILURE_ROLLBACK_SUCCESS");

  Reset(memory); f={}; f.protect_fail=1; f.restore_fail=1; TransactionOps o_ops=Ops(f); Session o_session_failure;
  auto o=o_session_failure.ApplySyntheticEditsForTest(o_ops,edits,detail);
  const bool o_qualified=o_session_failure.qualified(); const bool o_can_unload=o_session_failure.CanUnloadProvider();
  assert(o==TransactionResult::ApplyFailedRollbackFailed&&f.writes_to_after>=1&&f.write_calls>=2&&f.protect_calls>=3&&f.restore_calls>=2&&detail=="ROLLBACK_FAILED");
  assert(!o_qualified&&!o_can_unload);
  std::printf("TEST_O_LATE_MAKE_WRITABLE_FAILURE_ROLLBACK_FAILURE: PASS\nO: result=%s qualified=%s CanUnloadProvider=%s\n",ResultName(o),o_qualified?"true":"false",o_can_unload?"true":"false");
  return 0;
}
