cmake_minimum_required(VERSION 3.24)
project(dlssg_ampere_reference LANGUAGES CXX)

set(NGX_ROOT "" CACHE PATH "Path to a local NVIDIA DLSS SDK tree")
if(NOT NGX_ROOT)
  message(FATAL_ERROR "Set NGX_ROOT to the RenoDX external/DLSS tree")
endif()
add_executable(dlssg_ampere_reference
  standalone_host.cpp ampere_provider.cpp provider_transaction.cpp ampere_bridge.cpp
  ampere_provider.h ampere_bridge.h provider_transaction.h reference_core.hpp)
target_compile_features(dlssg_ampere_reference PRIVATE cxx_std_17)
target_compile_definitions(dlssg_ampere_reference PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_include_directories(dlssg_ampere_reference PRIVATE "${NGX_ROOT}/include")
target_link_directories(dlssg_ampere_reference PRIVATE "${NGX_ROOT}/lib/Windows_x86_64/x64")
target_link_libraries(dlssg_ampere_reference PRIVATE nvsdk_ngx_d d3d12 dxgi version bcrypt advapi32 user32 psapi)
if(MSVC)
  target_compile_options(dlssg_ampere_reference PRIVATE /W4 /EHsc /permissive-)
endif()
