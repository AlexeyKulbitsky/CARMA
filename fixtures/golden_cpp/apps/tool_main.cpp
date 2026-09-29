#include <cstdio>

#include "io/IoQueue.h"
#include "io/Platform.h"
#include "io/RingBuffer.h"

// Second main() in another target: the same canonical ID with two definitions.
int main() {
    golden::io::IoQueue queue;
    golden::io::RingBuffer<int> sizes;
    golden::io::RingBuffer<bool> flags;

    sizes.Push(static_cast<int>(queue.Read(golden::io::PlatformRoot()).size()));
    flags.Push(true);
    std::printf("%zu %zu\n", sizes.Size(), flags.Size());
    return 0;
}
