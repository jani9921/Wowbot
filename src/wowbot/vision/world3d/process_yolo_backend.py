"""Process-isolated Ultralytics backend for latency-stable live tracking.

The detector is deliberately a separate OS process. CUDA inference still uses
the selected NVIDIA device, while Python preprocessing/NMS, model warm-up and
occasional framework stalls can no longer hold the agent's GIL or its fast
OpenCV tracker thread. Requests are single-owner and bounded; stale work is
never allowed to become an unbounded frame queue.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from queue import Empty, Full
import time
from pathlib import Path
from typing import Any, Sequence

from .learned_detector import LearnedDetection, UltralyticsYoloBackend
from .shared_image_buffer import SharedBgrImageBuffer


def load_warm_backends(config: dict[str, Any]):
    """Load the primary (+ optional alternate-size) engine and warm both.

    Shared by the request/response worker below and the capture-driven feed
    worker; both run inside a spawned child process.
    """
    try:
        backend = UltralyticsYoloBackend(
            config["model_path"], device=config.get("device"),
            image_size=config["image_size"],
            max_detections=config["max_detections"],
            warmup_in_background=False,
        )
    except Exception:
        fallback_path = config.get("fallback_model_path")
        if not fallback_path:
            raise
        backend = UltralyticsYoloBackend(
            fallback_path, device=config.get("device"),
            image_size=config["image_size"],
            max_detections=config["max_detections"],
            warmup_in_background=False,
        )
    alternate = None
    alternate_path = config.get("alternate_model_path")
    if alternate_path:
        try:
            alternate = UltralyticsYoloBackend(
                alternate_path, device=config.get("device"),
                image_size=config["alternate_image_size"],
                max_detections=config["max_detections"],
                warmup_in_background=False,
            )
        except Exception:
            # A TensorRT engine may be incompatible after a driver/GPU
            # change. The primary backend remains fully functional.
            alternate = None
    # The direct backend loads synchronously. Run one explicit warm-up here
    # before advertising readiness; this cost stays entirely in the child.
    import numpy as np
    # rect=False makes every static TensorRT input square. One warm-up per
    # engine is sufficient regardless of the live client aspect ratio.
    for current in tuple(item for item in (backend, alternate) if item is not None):
        dummy = np.zeros((current.image_size, current.image_size, 3), dtype=np.uint8)
        current.predict(dummy, confidence=.90, iou=.45)
    return backend, alternate


def _worker_main(requests, results, status_messages, stopped, config: dict[str, Any]) -> None:
    """Load/warm the model and serve one bounded inference stream."""
    images = SharedBgrImageBuffer.attach(
        header_name=config["image_header_name"],
        data_name=config["image_data_name"], capacity=config["image_capacity"])
    try:
        backend, alternate = load_warm_backends(config)
        status_messages.put(("ready", backend.active_device, None))
    except Exception as exc:
        status_messages.put(("error", None, f"{type(exc).__name__}:{exc}"))
        images.close()
        return

    while not stopped.is_set():
        try:
            request = requests.get(timeout=.10)
        except Empty:
            continue
        if request is None:
            break
        request_id, image_sequence, confidence, iou, requested_size = request
        image = None
        try:
            image = images.view(image_sequence)
            selected = (alternate if alternate is not None
                        and int(requested_size or config["image_size"])
                        == int(config["alternate_image_size"]) else backend)
            detections = selected.predict(image, confidence=confidence, iou=iou)
            payload = tuple((item.label, item.confidence, item.left, item.top,
                             item.right, item.bottom) for item in detections)
            result = (request_id, payload, backend.active_device, None)
        except Exception as exc:
            result = (request_id, (), backend.active_device,
                      f"{type(exc).__name__}:{exc}")
        finally:
            # Release the ndarray's exported shared-memory view before the
            # worker can be asked to close its mapping.
            image = None
        # There is one caller and at most one in-flight request. A stale result
        # after a parent-side timeout may occupy the bounded mailbox; replace it
        # rather than blocking the CUDA worker indefinitely.
        try:
            results.put_nowait(result)
        except Full:
            try:
                results.get_nowait()
            except Empty:
                pass
            try:
                results.put_nowait(result)
            except Full:
                pass
    images.close()


class ProcessYoloBackend:
    """LearnedDetectorBackend implemented by a dedicated spawned process."""

    name = "ultralytics_yolo_process"

    def __init__(self, model_path: str | Path, *, device: str | int | None = None,
                 image_size: int = 640, max_detections: int = 20,
                 timeout_seconds: float = 30.,
                 alternate_model_path: str | Path | None = None,
                 alternate_image_size: int = 512,
                 fallback_model_path: str | Path | None = None) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(self.model_path)
        self.device = device
        self.image_size = max(320, int(image_size))
        self.max_detections = max(1, int(max_detections))
        self.timeout_seconds = max(2., float(timeout_seconds))
        alternate_path = Path(alternate_model_path) if alternate_model_path else None
        self.alternate_model_path = (
            alternate_path if alternate_path is not None and alternate_path.is_file() else None)
        self.alternate_image_size = max(320, int(alternate_image_size))
        self.supports_adaptive_image_size = self.alternate_model_path is not None
        fallback_path = Path(fallback_model_path) if fallback_model_path else None
        self.fallback_model_path = (
            fallback_path if fallback_path is not None and fallback_path.is_file() else None)
        self.transport = "shared_memory_bgr"
        self.last_image_size = self.image_size
        self.status = "warming"
        self.load_error: str | None = None
        self.active_device: str | None = None
        self._request_id = 0
        self._closed = False
        context = mp.get_context("spawn")
        self._stopped = context.Event()
        self._requests = context.Queue(maxsize=1)
        self._results = context.Queue(maxsize=2)
        self._status_messages = context.Queue(maxsize=4)
        self._images = SharedBgrImageBuffer.create(
            max_width=max(640, int(os.environ.get(
                "AIPC_YOLO_SHARED_MAX_WIDTH", "3840"))),
            max_height=max(480, int(os.environ.get(
                "AIPC_YOLO_SHARED_MAX_HEIGHT", "2160"))))
        image_header_name, image_data_name, image_capacity = self._images.descriptor
        self._process = context.Process(
            target=_worker_main,
            args=(self._requests, self._results, self._status_messages,
                  self._stopped, {
                      "model_path": str(self.model_path), "device": self.device,
                      "image_size": self.image_size,
                      "max_detections": self.max_detections,
                      "alternate_model_path": (str(self.alternate_model_path)
                                                 if self.alternate_model_path else None),
                      "alternate_image_size": self.alternate_image_size,
                      "fallback_model_path": (str(self.fallback_model_path)
                                                if self.fallback_model_path else None),
                      "image_header_name": image_header_name,
                      "image_data_name": image_data_name,
                      "image_capacity": image_capacity,
                  }),
            name="aipc-yolo-inference",
            daemon=True,
        )
        self._process.start()

    def _poll_status(self) -> None:
        while True:
            try:
                status, device, error = self._status_messages.get_nowait()
            except Empty:
                break
            self.status = str(status)
            self.active_device = device
            self.load_error = error
        if not self._closed and not self._process.is_alive() and self.status != "error":
            self.status = "error"
            self.load_error = f"yolo_process_exited:{self._process.exitcode}"

    def predict(self, bgr_roi: Any, *, confidence: float,
                iou: float) -> Sequence[LearnedDetection]:
        return self.predict_at_size(
            bgr_roi, confidence=confidence, iou=iou, image_size=self.image_size)

    def predict_at_size(self, bgr_roi: Any, *, confidence: float, iou: float,
                        image_size: int) -> Sequence[LearnedDetection]:
        self.last_image_size = int(image_size)
        self._poll_status()
        if self._closed:
            return ()
        if self.status == "warming":
            return ()
        if self.status == "error":
            raise RuntimeError(self.load_error or "YOLO process failed")
        self._request_id += 1
        request_id = self._request_id
        try:
            image_sequence = self._images.write(bgr_roi)
            self._requests.put_nowait(
                (request_id, image_sequence, float(confidence), float(iou), int(image_size)))
        except (Full, ValueError):
            # This should not occur with the single detector owner, but a busy
            # mailbox means the newest frame must be dropped, never queued.
            return ()
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if not self._process.is_alive():
                self.status = "error"
                self.load_error = f"yolo_process_exited:{self._process.exitcode}"
                raise RuntimeError(self.load_error)
            try:
                completed_id, payload, device, error = self._results.get(timeout=.10)
            except Empty:
                continue
            if completed_id != request_id:
                continue
            self.active_device = device
            if error:
                self.load_error = error
                raise RuntimeError(error)
            return tuple(LearnedDetection(*row) for row in payload)
        self.status = "ready"
        self.load_error = "yolo_process_timeout"
        return ()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stopped.set()
        try:
            self._requests.put_nowait(None)
        except Full:
            pass
        self._process.join(timeout=3.)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.)
        for queue in (self._requests, self._results, self._status_messages):
            queue.close()
        self._images.close()
        self._images.unlink()
