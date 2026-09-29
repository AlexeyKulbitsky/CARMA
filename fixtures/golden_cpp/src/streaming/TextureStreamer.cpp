#include "streaming/TextureStreamer.h"

#include "io/IoQueue.h"
#include "render/backend/GpuUploader.h"

namespace golden::streaming {

// Same name and signature as the static Clamp in io/IoQueue.cpp: the file segment keeps the IDs apart.
static int Clamp(int value) {
    return value < 0 ? 0 : value;
}

TextureStreamer::TextureStreamer(io::IoQueue& queue) : m_queue(queue) {}

void TextureStreamer::RequestLoad(const std::string& name) {
    m_pending = Clamp(m_pending + 1);
    m_lastHandle.id = m_pending;
    // Async hop: the lambda runs later inside IoQueue::Process(). The call graph attributes
    // the OnLoaded call to RequestLoad (the lambda's enclosing function), never to Process.
    m_queue.Submit([this, name] { OnLoaded(name); });
}

void TextureStreamer::OnLoaded(const std::string& name) {
    m_pending = Clamp(m_pending - 1);
    // streaming -> render: not declared in the model, closes the render <-> streaming cycle.
    render::GpuUploader::Upload(name);
}

int TextureStreamer::Pending() const {
    return m_pending;
}

}  // namespace golden::streaming
