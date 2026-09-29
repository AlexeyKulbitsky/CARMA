#include "fakelib/fakelib.h"

namespace fakelib {

unsigned Hash(const char* text) {
    unsigned hash = 2166136261u;
    for (; *text; ++text) {
        hash = (hash ^ static_cast<unsigned char>(*text)) * 16777619u;
    }
    return hash;
}

}  // namespace fakelib
