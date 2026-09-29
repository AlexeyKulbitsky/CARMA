#pragma once

#include "core/Component.h"
#include "render/IRenderable.h"

namespace golden::render {

class Mesh : public core::Component, public IRenderable {
    GOLDEN_COMPONENT(Mesh)

public:
    void Draw() override;
    int DrawCount() const { return m_drawCount; }

private:
    int m_drawCount = 0;
};

}  // namespace golden::render
