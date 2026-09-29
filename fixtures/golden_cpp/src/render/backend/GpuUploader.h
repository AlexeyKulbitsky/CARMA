#pragma once

#include <string>

namespace golden::render {

class GpuUploader {
public:
    static void Upload(const std::string& texture);
    static int UploadedCount();
};

}  // namespace golden::render
