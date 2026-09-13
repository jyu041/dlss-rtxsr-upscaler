#pragma once

#include <windows.h>
#include <cstdint>
#include <string>
#include <vector>

namespace ampere_provider {

struct TransactionOps;
enum class TransactionResult;

inline constexpr char kExpectedSha256[] = "15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5";
inline constexpr uint32_t kNativeArchitecture = 0x170;
inline constexpr uint32_t kAdaArchitecture = 0x190;
inline constexpr char kExpectedVersion[] = "310.2.1.0";

struct Edit { uint8_t* address{}; uint8_t before{}; uint8_t after{}; };

class Session {
 public:
#ifdef AMPERE_PROVIDER_TESTING
  TransactionResult ApplySyntheticEditsForTest(const TransactionOps& ops, const std::vector<Edit>& edits, std::string& detail);
#endif
  bool LoadAndAdapt(const std::wstring& absolute_path, std::string& detail);
  bool InspectOnly(const std::wstring& absolute_path, std::string& detail,
                   size_t& edit_count, size_t& hidden_cubins);
  bool VerifyReadback(std::string& detail) const;
  bool Rollback();
  bool Unload();
  bool Restored() const { return rollback_verified_ && edits_.empty(); }
  bool CanUnloadProvider() const { return !qualified_ && rollback_verified_ && edits_.empty(); }
  HMODULE module() const { return module_; }
  size_t edit_count() const { return edits_.size(); }
  size_t hidden_cubins() const { return hidden_cubins_; }
  size_t provider_arch_gate_count() const { return provider_arch_gate_count_; }
  bool qualified() const { return qualified_; }
  ~Session() { Rollback(); Unload(); }

 private:
  void ConsumeApplyResult(TransactionResult result, const std::vector<Edit>& edits);
  HMODULE module_{};
  std::vector<Edit> edits_;
  size_t hidden_cubins_{};
  size_t provider_arch_gate_count_{};
  bool qualified_{};
  bool rollback_verified_{true};
  std::wstring canonical_path_;
};

}  // namespace ampere_provider
