# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Builds kernel_bench against an NVBench source tree given as NVBENCH_SOURCE.

cmake_minimum_required(VERSION 3.30.4)
project(pairbench_showcase_gpu_kernel LANGUAGES CXX CUDA)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(NVBench_ENABLE_EXECUTABLES OFF CACHE BOOL "" FORCE)
set(NVBench_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(NVBench_ENABLE_EXAMPLES OFF CACHE BOOL "" FORCE)
add_subdirectory(${NVBENCH_SOURCE} nvbench)

add_executable(kernel_bench kernel_bench.cu)
target_link_libraries(kernel_bench PRIVATE nvbench::main)
target_compile_features(kernel_bench PRIVATE cxx_std_17)
set_target_properties(kernel_bench PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
