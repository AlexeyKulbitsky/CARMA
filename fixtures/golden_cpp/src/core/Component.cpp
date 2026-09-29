#include "core/Component.h"

namespace golden::core {

std::size_t Component::NextTypeId() {
    static std::size_t next = 0;
    return next++;
}

}  // namespace golden::core
