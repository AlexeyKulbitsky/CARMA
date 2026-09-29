#include "render/backend/GpuUploader.h"

namespace golden::render {

namespace {
// Internal linkage: the ID carries the file segment in place of the anonymous namespace.
int g_uploaded = 0;
}  // namespace

void GpuUploader::Upload(const std::string& texture) {
    if (!texture.empty()) {
        ++g_uploaded;
    }
}

int GpuUploader::UploadedCount() {
    return g_uploaded;
}

}  // namespace golden::render
