#pragma once

#include <cstddef>
#include <functional>
#include <string>
#include <vector>

namespace golden::io {

class IoQueue {
public:
    void Submit(std::function<void()> task);
    void Process();

    // One overload takes std::size_t: its ID must be the same on every OS.
    std::string Read(const std::string& path);
    std::string Read(std::size_t offset);

    // A plain overload and a function template with the same parameter types.
    void Enqueue(const std::string& name);
    template <typename T>
    void Enqueue(const std::string& name) {
        Enqueue(name + ":" + T::kTag);
    }

private:
    std::vector<std::function<void()>> m_tasks;
};

}  // namespace golden::io
