cmake_minimum_required(VERSION 3.20)
project(golden_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Vendored stub inside the project root: CARMA maps it to _external by the ignore globs.
add_library(fakelib STATIC thirdparty/fakelib/fakelib.cpp)
target_include_directories(fakelib PUBLIC thirdparty)

add_library(golden_core STATIC
    src/core/Component.cpp
    src/render/Renderer.cpp
    src/render/backend/GpuUploader.cpp
    src/render/backend/Mesh.cpp
    src/streaming/TextureStreamer.cpp
    src/io/IoQueue.cpp
    src/io/Platform.cpp
)
target_include_directories(golden_core PUBLIC src)
target_link_libraries(golden_core PUBLIC fakelib)

# Two executables, each with its own main(): one canonical ID, two definitions.
add_executable(golden_app apps/app_main.cpp)
target_link_libraries(golden_app PRIVATE golden_core)

add_executable(golden_tool apps/tool_main.cpp)
target_link_libraries(golden_tool PRIVATE golden_core)
