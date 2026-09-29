#include "render/Renderer.h"

#include <algorithm>
#include <cstdlib>

#include "streaming/TextureStreamer.h"

namespace golden::render {

// Global initializer: the call has no enclosing function or class (container: null).
static const int kDefaultWidth = ComputeDefaultWidth();

Renderer::Renderer(streaming::TextureStreamer& streamer) : m_streamer(streamer) {}

void Renderer::DrawScene() {
    // Local type and lambda are not facts; their references belong to DrawScene.
    struct DrawStats {
        int drawn = 0;
    };
    DrawStats stats;
    auto drawOne = [&stats](IRenderable* item) {
        item->Draw();
        ++stats.drawn;
    };
    std::for_each(m_items.begin(), m_items.end(), drawOne);
    ++m_stats.frame;

    m_streamer.RequestLoad("sky.dds");

    // Taking the address without calling it: a reference, not a call.
    std::atexit(&OnShutdown);
}

void Renderer::Add(IRenderable* item) {
    m_items.push_back(item);
}

int Renderer::Width() const {
    return kDefaultWidth;
}

int ComputeDefaultWidth() {
    return 1280;
}

void OnShutdown() {}

}  // namespace golden::render
