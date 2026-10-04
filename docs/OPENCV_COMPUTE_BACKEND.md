# OpenCV compute backend

The World Map OpenCV preprocessing paths and the World3D luminance/downsample
stage use `wowbot.vision.opencv_backend.OpenCvComputeBackend`.

## Selection

Set `WOWBOT_OPENCV_BACKEND` before starting the agent:

```powershell
$env:WOWBOT_OPENCV_BACKEND = "AUTO"  # recommended
$env:WOWBOT_OPENCV_BACKEND = "CUDA"  # request CUDA, still safely falls back
$env:WOWBOT_OPENCV_BACKEND = "CPU"   # force CPU
```

`AUTO` selects CUDA only when all of the following are true:

1. OpenCV exposes `cv2.cuda` and `cv2.cuda_GpuMat`;
2. `cv2.cuda.getCudaEnabledDeviceCount()` returns at least one device;
3. every CUDA primitive required by the fused preprocessing batches exists.

Module presence is not enough.  Standard Python OpenCV wheels often expose a
`cuda` namespace but are compiled without CUDA device support.

AMD, Intel, a CPU-only OpenCV build, an unavailable CUDA runtime, or an error in
an individual CUDA batch automatically uses the equivalent CPU implementation.
The runtime does not disable vision and does not reinterpret results.

## Accelerated batches

- image downsampling;
- RGB→gray / RGB→HSV conversion;
- Gaussian and box filtering;
- Canny edge extraction;
- morphological close;
- absolute-difference contrast calculation.
- World3D BGRA→gray conversion and detector/tracker downsampling.

Connected components, line-segment detection, World3D phase correlation,
patch comparison, proposal scoring and all semantic/evidence layers remain on
CPU. Diagnostics therefore report CUDA only for preprocessing batches that
actually executed there; the complete World3D pipeline is not mislabeled as a
GPU detector.

The backend keeps one upload/download boundary around each fused batch to avoid
turning PCIe transfers into the bottleneck.

## Diagnostics

Every extractor exposes `compute_diagnostics`, including:

```text
requested
active
cuda_device_count
cuda_available
reason
accelerated_batches
cpu_batches
runtime_fallbacks
last_fallback_reason
```

On the development machine at implementation time, an RTX 2050 was present but
OpenCV 5.0.0 reported zero CUDA-enabled devices and a CPU-only build.  `AUTO`
therefore correctly selected CPU.  Actual CUDA execution requires an OpenCV
build compiled against the installed NVIDIA CUDA runtime.

## Verification

`tests/test_opencv_compute_backend.py` checks explicit CPU operation, AUTO
selection, invalid configuration rejection, CUDA-request fallback, both World
Map extractor integrations and the shared World3D V2/V3 preprocessing path.
Hardware-specific CUDA performance must be
benchmarked on a CUDA-enabled OpenCV installation; CPU fallback tests are not
evidence that a particular CUDA wheel works on a target PC.
