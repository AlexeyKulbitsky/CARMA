#pragma once

// Generates a whole struct, like engine reflection macros do.
#define GOLDEN_DECLARE_HANDLE(Name) \
    struct Name {                   \
        int id = 0;                 \
    }

namespace golden::io {

GOLDEN_DECLARE_HANDLE(FileHandle);
GOLDEN_DECLARE_HANDLE(RequestHandle);

}  // namespace golden::io
