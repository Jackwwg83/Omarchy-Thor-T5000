// CUDA smoke test for the Jetson AGX Thor (Slice 3): device query, a kernel over unified memory
// checked on the host, and one cuBLAS SGEMM checked against a CPU reference.
//
//   nvcc -arch=sm_110 -O2 -o cuda-smoke tests/cuda-smoke.cu -lcublas && ./cuda-smoke
//
// Exit 0 only if every check passes; the output is the evidence. CUDA_SMOKE_INJECT_NAN=1 puts a
// NaN into the SGEMM result, which must fail.
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <chrono>
#include <cublas_v2.h>
#include <cuda_runtime.h>

#define CHECK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { \
  std::printf("FAIL %s: %s\n", #x, cudaGetErrorString(e)); return 1; } } while (0)
#define CHECK_BLAS(x) do { cublasStatus_t s = (x); if (s != CUBLAS_STATUS_SUCCESS) { \
  std::printf("FAIL %s: cublas status %d\n", #x, (int)s); return 1; } } while (0)

__global__ void saxpy(int n, float a, const float *x, float *y) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < n) y[i] = a * x[i] + y[i];
}

int main() {
  int driver = 0, runtime = 0, count = 0;
  CHECK(cudaDriverGetVersion(&driver));
  CHECK(cudaRuntimeGetVersion(&runtime));
  CHECK(cudaGetDeviceCount(&count));
  if (count < 1) { std::printf("FAIL no CUDA device\n"); return 1; }
  cudaDeviceProp p;
  CHECK(cudaGetDeviceProperties(&p, 0));
  std::printf("device: %s, sm_%d%d, %d SMs, %.1f GiB, integrated=%d, driver %d, runtime %d\n",
              p.name, p.major, p.minor, p.multiProcessorCount, p.totalGlobalMem / 1073741824.0,
              p.integrated, driver, runtime);

  // Unified memory: written on the host, updated on the GPU, read back on the host.
  const int n = 1 << 24;
  float *x, *y;
  CHECK(cudaMallocManaged(&x, n * sizeof(float)));
  CHECK(cudaMallocManaged(&y, n * sizeof(float)));
  for (int i = 0; i < n; i++) { x[i] = (float)(i % 1000); y[i] = 1.0f; }
  auto t0 = std::chrono::steady_clock::now();
  saxpy<<<(n + 255) / 256, 256>>>(n, 2.0f, x, y);
  CHECK(cudaGetLastError());
  CHECK(cudaDeviceSynchronize());
  double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  int bad = 0;
  for (int i = 0; i < n; i++) if (y[i] != 2.0f * (float)(i % 1000) + 1.0f) bad++;
  std::printf("unified memory saxpy: %d elements, %d wrong, %.2f ms\n", n, bad, ms);
  if (bad) return 1;

  // cuBLAS SGEMM, C = A * B, checked against a CPU reference.
  const int m = 512;
  float *a, *b, *c;
  CHECK(cudaMallocManaged(&a, m * m * sizeof(float)));
  CHECK(cudaMallocManaged(&b, m * m * sizeof(float)));
  CHECK(cudaMallocManaged(&c, m * m * sizeof(float)));
  for (int i = 0; i < m * m; i++) { a[i] = (float)((i * 7) % 13) / 13.0f; b[i] = (float)((i * 3) % 11) / 11.0f; }
  cublasHandle_t h;
  CHECK_BLAS(cublasCreate(&h));
  const float one = 1.0f, zero = 0.0f;
  t0 = std::chrono::steady_clock::now();
  CHECK_BLAS(cublasSgemm(h, CUBLAS_OP_N, CUBLAS_OP_N, m, m, m, &one, a, m, b, m, &zero, c, m));
  CHECK(cudaDeviceSynchronize());
  ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  if (std::getenv("CUDA_SMOKE_INJECT_NAN")) c[m + 1] = std::nanf("");  // negative check: must FAIL
  // A NaN or Inf result fails outright: fmax would skip NaN and report a clean error.
  double max_err = 0;
  int nonfinite = 0;
  for (int col = 0; col < m; col++)
    for (int row = 0; row < m; row++) {
      double ref = 0;
      for (int k = 0; k < m; k++) ref += (double)a[k * m + row] * (double)b[col * m + k];  // column-major
      float got = c[col * m + row];
      if (!std::isfinite(got)) { nonfinite++; continue; }
      max_err = std::fmax(max_err, std::fabs(ref - got));
    }
  std::printf("cublas sgemm %dx%d: max abs error %.2e, %d non-finite, %.2f ms\n", m, m, max_err, nonfinite, ms);
  cublasDestroy(h);
  if (nonfinite || !(max_err <= 1e-2)) { std::printf("FAIL sgemm result wrong\n"); return 1; }
  std::printf("PASS\n");
  return 0;
}
