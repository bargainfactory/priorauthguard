cmake_minimum_required(VERSION 3.22)
project(pa_guard_whisper CXX)

set(CMAKE_CXX_STANDARD 17)

# whisper.cpp is fetched as a submodule under third_party/whisper.cpp; tag
# pinned in the plugin's release notes.
add_subdirectory(third_party/whisper.cpp EXCLUDE_FROM_ALL)

add_library(pa_guard_whisper SHARED whisper-jni.cpp)
target_include_directories(pa_guard_whisper PRIVATE third_party/whisper.cpp)
target_link_libraries(pa_guard_whisper PRIVATE whisper log)
