#pragma once

#include <vector>

#include "core/FrameStats.h"
#include "render/IRenderable.h"

namespace golden::streaming {
class TextureStreamer;
}

namespace golden::render {

// Lives directly in src/render/, while render also has a child component (backend):
// its symbols belong to the parent and show up as the render._self node.
class Renderer {
public:
    explicit Renderer(streaming::TextureStreamer& streamer);
    void DrawScene();
    void Add(IRenderable* item);
    int Width() const;

private:
    // Field of a type from another subsystem: a use edge from the class container.
    streaming::TextureStreamer& m_streamer;
    std::vector<IRenderable*> m_items;
    core::FrameStats m_stats{};
};

int ComputeDefaultWidth();
void OnShutdown();

}  // namespace golden::render
