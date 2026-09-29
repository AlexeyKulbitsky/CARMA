#include "io/Platform.h"

namespace golden::io {

// The only deliberate platform fork in the fixture (see expected/README.md):
// WindowsDriveRoot exists only in facts indexed on Windows.
#if defined(_WIN32)
static std::string WindowsDriveRoot() {
    return "C:/";
}

std::string PlatformRoot() {
    return WindowsDriveRoot();
}
#else
std::string PlatformRoot() {
    return "/";
}
#endif

}  // namespace golden::io
