#include "io/IoQueue.h"

#include <utility>

#include "fakelib/fakelib.h"

namespace golden::io {

// Same name and signature as the static Clamp in streaming/TextureStreamer.cpp.
static int Clamp(int value) {
    return value > 1024 ? 1024 : value;
}

namespace {
// Anonymous namespace: internal linkage, the file segment replaces the namespace in the ID.
std::string Normalize(const std::string& path) {
    return path.empty() ? std::string("/") : path;
}
}  // namespace

void IoQueue::Submit(std::function<void()> task) {
    m_tasks.push_back(std::move(task));
}

void IoQueue::Process() {
    // Runs the stored lambdas: these calls are invisible to the static call graph.
    for (auto& task : m_tasks) {
        task();
    }
    m_tasks.clear();
}

std::string IoQueue::Read(const std::string& path) {
    // Call into the vendored library: lands in _external.
    const unsigned hash = fakelib::Hash(Normalize(path).c_str());
    return std::to_string(Clamp(static_cast<int>(hash % 2048u)));
}

std::string IoQueue::Read(std::size_t offset) {
    return Read(std::to_string(offset));
}

void IoQueue::Enqueue(const std::string& name) {
    m_tasks.push_back([name] { (void)name; });
}

}  // namespace golden::io
