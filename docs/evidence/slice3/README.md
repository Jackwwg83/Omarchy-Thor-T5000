# Slice 3 evidence: CUDA 13.2, GPU containers and Ollama on the Jetson AGX Thor

2026-09-26, owner at the Thor for the reboots; checks over SSH. Every row is **real data** from the
Thor unless marked otherwise.

## Rehearsal (nothing installed: debs and tarballs unpacked in scratch directories)

| Check | Result |
|---|---|
| nvcc 13.2 with gcc 16 | `-allow-unsupported-compiler` alone: 100 errors in libstdc++ 16 headers (`char8_t`, `__builtin_is_virtual_base_of`): gcc 16 defaults to C++20 (`__cplusplus 202002L`). With `-std=c++17`: builds |
| libcuda dependencies | with only cuda-openrm: SIGSEGV in `cuDevicePrimaryCtxRetain` (NULL call); `LD_DEBUG` shows libcuda loading `libnvcucompat.so`, `libnvcuextend.so` from nvidia-l4t-cuda; with them: PASS |
| Ollama v0.34.4 official arm64 | `library=CUDA compute=11.0 description="NVIDIA Thor" libdirs=ollama,cuda_v13 type=iGPU`; qwen3:1.7b 29/29 layers on the GPU; first load 45.7 s at 0.5 tok/s (PTX compiled for sm_110), then 47.7 tok/s |
| nvidia-ctk 1.20 CSV mode | NVIDIA's devices.csv/drivers.csv entries missing under OpenRM are skipped with a warning: no filtering needed |

## Installed (published to `[raytone-thor]`, `omarchy-update -y`, then `pacman -S raytone-thor-cuda raytone-thor-ollama`)

| Component | State | Evidence |
|---|---|---|
| libcuda (raytone-thor-core 39.2.1-5) | **real data** | `nvidia-smi`: `CUDA Version: 13.2` (was N/A); `ldconfig -p`: `libcuda.so.1 => /opt/nvidia/l4t-gpu-libs/openrm/libcuda.so.1` |
| CUDA toolkit (raytone-thor-cuda 13.2.86-1) | **real data** | `nvcc` from `/usr/local/cuda/bin` with `NVCC_PREPEND_FLAGS=-allow-unsupported-compiler -std=c++17`; `tests/cuda-smoke.cu` built with `-arch=sm_110`: `NVIDIA Thor, sm_110, 20 SMs, 122.9 GiB, integrated=1, driver 13020, runtime 13020`; unified memory saxpy 16777216 elements, 0 wrong; cuBLAS SGEMM 512x512 max abs error 6.77e-05; PASS |
| Ollama service (raytone-thor-ollama) | **real data** | first run found only the CPU: `NvRmMemInitNvmap failed: error Permission denied` (`/dev/nvmap` root:video 0660); fixed in 0.34.4-2 (`m ollama video`), applied by hand on the drive until published: `100% GPU`, `/usr/lib/ollama/llama-server` 6174 MiB in `nvidia-smi`, 140 tok/s once loaded, answer correct |
| Sustained load | **real data** (21 s only) | 2181 tokens at 105.2 tok/s; GPU 1386 MHz steady, 87–94 % busy, ~28 W, 44 → 53 °C, back to 315 MHz and 46 °C after |
| CDI / Docker (raytone-thor-omarchy 0.1.0-6 → -7) | **real data** | `docker info`: CDI spec dirs `/etc/cdi`, `/run/cdi`; devices `nvidia.com/gpu=0`, `nvidia.com/gpu=all`; spec: 83 host paths, all present. `nvcr.io/nvidia/cuda:13.2.0-runtime-ubuntu24.04` with `--device nvidia.com/gpu=all` runs the smoke binary: PASS, same numbers as on the host |
| CDI at boot | **real data** after the fix | 0.1.0-6 generated the spec before `nv-load-display-modules` finished: transient `/dev/dri/card0`, no `/dev/nvidia0`/`nvidia-uvm`, `docker: failed to stat CDI host device "/dev/dri/card0"`. 0.1.0-7 orders it after (display stack done 21:18:32.98, spec 21:18:33.70): all nodes, container PASS after a clean boot |
| Boot | **real data** | two reboots: Omarchy by default, no failed units; Ollama active on CUDA; headphone route set |

`omarchy-update` logs `error: unable to run hook nvidia-ctk-cdi.hook: could not satisfy dependencies`:
the toolkit's own hook needs desktop `nvidia-utils` and reads `/usr/lib/libcuda.so`; it does not apply
on the Thor and changes nothing. The Thor's spec comes from `raytone-thor-cdi.service`.

## State

- raytone-thor-omarchy 0.1.0-7 (CDI ordering) and raytone-thor-ollama 0.34.4-2 (video group) are built
  and tested on the drive but not yet published (0.1.0-7 installed with `pacman -U`, the group added
  with `usermod`): the next JetPack round publishes them.
- Not in this slice: cuDNN, TensorRT; a longer thermal soak.
