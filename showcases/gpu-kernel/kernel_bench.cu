// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026, Eugo, Inc.
//
// Two GPU benchmarks for NVBench: a hand-written SAXPY kernel, and a sum
// with CUB's device-wide reduction. With PAIRBENCH_WORK_FACTOR=N each
// measured launch processes N times the elements of its axis value.

#include <nvbench/nvbench.cuh>

#include <cub/device/device_reduce.cuh>
#include <thrust/device_vector.h>

#include <cstdlib>

namespace
{

std::size_t work_factor()
{
  const char *text = std::getenv("PAIRBENCH_WORK_FACTOR");
  const long value = text ? std::strtol(text, nullptr, 10) : 1;
  return value > 0 ? static_cast<std::size_t>(value) : 1;
}

__global__ void saxpy_kernel(float a, const float *x, float *y, std::size_t n)
{
  const std::size_t i = blockIdx.x * static_cast<std::size_t>(blockDim.x) + threadIdx.x;
  if (i < n)
  {
    y[i] = a * x[i] + y[i];
  }
}

void saxpy(nvbench::state &state)
{
  const auto n = static_cast<std::size_t>(state.get_int64("Elements")) * work_factor();
  thrust::device_vector<float> x(n, 1.0f);
  thrust::device_vector<float> y(n, 2.0f);
  state.add_element_count(n);
  state.add_global_memory_reads<float>(2 * n);
  state.add_global_memory_writes<float>(n);

  const unsigned threads = 256;
  const auto blocks = static_cast<unsigned>((n + threads - 1) / threads);
  state.exec([&](nvbench::launch &launch) {
    saxpy_kernel<<<blocks, threads, 0, launch.get_stream()>>>(
      2.5f, thrust::raw_pointer_cast(x.data()), thrust::raw_pointer_cast(y.data()), n);
  });
}

void cub_sum(nvbench::state &state)
{
  const auto n = static_cast<std::size_t>(state.get_int64("Elements")) * work_factor();
  thrust::device_vector<float> in(n, 1.0f);
  thrust::device_vector<float> out(1);
  std::size_t temp_bytes = 0;
  cub::DeviceReduce::Sum(nullptr, temp_bytes, thrust::raw_pointer_cast(in.data()),
                         thrust::raw_pointer_cast(out.data()), n);
  thrust::device_vector<unsigned char> temp(temp_bytes);
  state.add_element_count(n);
  state.add_global_memory_reads<float>(n);

  state.exec([&](nvbench::launch &launch) {
    cub::DeviceReduce::Sum(thrust::raw_pointer_cast(temp.data()), temp_bytes,
                           thrust::raw_pointer_cast(in.data()),
                           thrust::raw_pointer_cast(out.data()), n, launch.get_stream());
  });
}

} // namespace

NVBENCH_BENCH(saxpy).add_int64_power_of_two_axis("Elements", {24, 26});
NVBENCH_BENCH(cub_sum).add_int64_power_of_two_axis("Elements", {24, 26});
