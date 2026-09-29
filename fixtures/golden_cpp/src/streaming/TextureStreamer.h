#pragma once

#include <string>

#include "core/Component.h"
#include "io/Handles.h"

namespace golden::io {
class IoQueue;
}

namespace golden::streaming {

class TextureStreamer : public core::Component {
    GOLDEN_COMPONENT(TextureStreamer)

public:
    explicit TextureStreamer(io::IoQueue& queue);
    void RequestLoad(const std::string& name);
    void OnLoaded(const std::string& name);
    int Pending() const;

private:
    io::IoQueue& m_queue;
    // Field of a type from another subsystem: a use edge from the class container.
    io::FileHandle m_lastHandle{};
    int m_pending = 0;
};

}  // namespace golden::streaming
