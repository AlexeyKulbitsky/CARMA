#pragma once

#include <cstddef>

namespace golden::core {

class Component {
public:
    virtual ~Component() = default;
    virtual std::size_t GetTypeId() const = 0;

protected:
    template <typename T>
    static std::size_t StaticTypeId() {
        static const std::size_t id = NextTypeId();
        return id;
    }

private:
    static std::size_t NextTypeId();
};

}  // namespace golden::core

// Adds type-id methods to a component class, like COMPONENT(...) in gd-engine.
// The generated methods belong where the macro is expanded, not to this header.
#define GOLDEN_COMPONENT(ComponentClass)                                              \
public:                                                                               \
    static std::size_t TypeId() { return Component::StaticTypeId<ComponentClass>(); } \
    std::size_t GetTypeId() const override { return TypeId(); }
