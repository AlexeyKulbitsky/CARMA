#include "io/IoQueue.h"
#include "render/Renderer.h"
#include "render/backend/Mesh.h"
#include "streaming/TextureStreamer.h"

int main() {
    golden::io::IoQueue queue;
    golden::streaming::TextureStreamer streamer(queue);
    golden::render::Renderer renderer(streamer);
    golden::render::Mesh mesh;

    renderer.Add(&mesh);
    renderer.DrawScene();
    queue.Process();
    return streamer.Pending();
}
