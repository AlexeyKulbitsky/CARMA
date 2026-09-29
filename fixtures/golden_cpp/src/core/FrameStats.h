#pragma once

namespace golden::core {

// Anonymous union and struct are transparent: their fields are fields of FrameStats.
struct FrameStats {
    union {
        struct {
            float cpuMs;
            float gpuMs;
        };
        float timings[2];
    };
    int frame = 0;
};

}  // namespace golden::core
