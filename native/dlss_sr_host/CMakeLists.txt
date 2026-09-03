cmake_minimum_required(VERSION 3.24)
project(dlss_sr_host LANGUAGES CXX)

if(NOT DEFINED NGX_SDK_ROOT)
    set(NGX_SDK_ROOT "${CMAKE_SOURCE_DIR}/../../third_party/local/nvidia-dlss-sdk-full")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

add_executable(dlss_sr_host main.cpp)
target_include_directories(dlss_sr_host PRIVATE "${NGX_SDK_ROOT}/include")
target_link_directories(dlss_sr_host PRIVATE "${NGX_SDK_ROOT}/lib/Windows_x86_64/khr/x64")
target_link_libraries(dlss_sr_host PRIVATE nvsdk_ngx_khr_s d3d12 dxgi dxguid advapi32 user32 windowscodecs)
target_compile_definitions(dlss_sr_host PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_compile_options(dlss_sr_host PRIVATE /W4 /EHsc /permissive-)
target_link_options(dlss_sr_host PRIVATE /SUBSYSTEM:CONSOLE)

set_target_properties(dlss_sr_host PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/../../runtime/dlss-sr-host"
    RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_SOURCE_DIR}/../../runtime/dlss-sr-host"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/../../runtime/dlss-sr-host")
