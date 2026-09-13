#pragma once
#include "ampere_provider.h"
#include <string>
#include <vector>

namespace ampere_provider {
enum class TransactionResult { Applied, ApplyFailed, ApplyFailedRollbackSucceeded, ApplyFailedRollbackFailed, RollbackSucceeded, RollbackFailed };
struct TransactionOps {
    void *context{};
    bool (*make_writable)(void *, uint8_t *, DWORD *){};
    bool (*restore)(void *, uint8_t *, DWORD){};
    bool (*read)(void *, uint8_t *, uint8_t *){};
    bool (*write)(void *, uint8_t *, uint8_t){};
    bool (*flush)(void *, uint8_t *, size_t){};
};
TransactionOps WindowsTransactionOps();
bool ValidateEdits(const std::vector<Edit> &, std::string &);
TransactionResult ApplyEdits(const std::vector<Edit> &, const TransactionOps &, std::vector<size_t> &, std::string &);
TransactionResult RollbackEdits(const std::vector<Edit> &, const std::vector<size_t> &, const TransactionOps &, std::string &);
}
