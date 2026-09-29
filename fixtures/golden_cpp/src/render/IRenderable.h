#pragma once

namespace golden::render {

class IRenderable {
public:
    virtual ~IRenderable() = default;
    virtual void Draw() = 0;
};

}  // namespace golden::render
