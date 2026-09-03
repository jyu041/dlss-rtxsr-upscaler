cmake_minimum_required(VERSION 3.24)
project(nvof_probe LANGUAGES CXX)

if(NOT DEFINED NVOF_SDK_ROOT)
    set(NVOF_SDK_ROOT "${CMAKE_SOURCE_DIR}/../../third_party/local/nvidia-optical-flow-sdk-5.0.7/Optical_Flow_SDK_5.0.7")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

add_executable(nvof_probe main.cpp)
target_include_directories(nvof_probe PRIVATE "${NVOF_SDK_ROOT}/NvOFInterface")
target_link_libraries(nvof_probe PRIVATE d3d12 dxgi bcrypt)
target_compile_definitions(nvof_probe PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_compile_options(nvof_probe PRIVATE /W4 /EHsc /permissive-)
target_link_options(nvof_probe PRIVATE /SUBSYSTEM:CONSOLE)
set_target_properties(nvof_probe PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../../runtime/benchmarks/dlss-sr/nvof")
