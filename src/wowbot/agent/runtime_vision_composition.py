"""Optional legacy vision composition; server profile creates no workers."""
import os


def configure_vision(runtime, output, world3d_model, vision):
    runtime.perception = None
    if vision:
        from .perception import PerceptionWorker
        from wowbot.vision.world3d.learned_detector import build_runtime_learned_detector
        learned_detector = build_runtime_learned_detector(
            world3d_model, capture_handle=runtime._capture_process_handle)
        if (callable(getattr(learned_detector, "set_trace_path", None))
                and os.environ.get("AIPC_FEED_TRACE", "1").strip() != "0"):
            # Per-frame detector association record for offline replay.
            learned_detector.set_trace_path(output / "feed_association_trace.jsonl")
        live_vision_monitor = None
        if os.environ.get("AIPC_LIVE_VISION", "").strip().lower() in {
                "1", "true", "yes", "on"}:
            from wowbot.diagnostics.live_vision_monitor import LiveVisionMonitor
            live_vision_monitor = LiveVisionMonitor(
                maximum_hz=float(os.environ.get("AIPC_LIVE_VISION_HZ", "60")))
        runtime._live_vision_monitor = live_vision_monitor
        proposal_mode = os.environ.get("AIPC_WORLD3D_PROPOSAL_MODE", "YOLO_ONLY")
        if (os.environ.get("AIPC_WORLD3D_PROCESS", "1").strip() != "0"
                and runtime._capture_process_handle is not None
                and getattr(learned_detector, "capture_driven", False)):
            # World3D perception in its own process (own GIL): see
            # perception_process.py.  The feed pipeline is started here
            # because that process only holds a client endpoint.
            from .perception_process import ProcessPerceptionWorker
            learned_detector.start_pipeline(
                proposal_mode=str(proposal_mode).strip().upper(),
                tracker_mode=str(os.getenv("AIPC_WORLD3D_TRACKER", "AUTO"))
                .strip().lower().replace("-", ""))
            runtime.perception = ProcessPerceptionWorker(
                capture_ring=runtime._capture_process_handle.client.ring_name,
                feed=learned_detector, live_vision_monitor=live_vision_monitor,
                hard_example_directory=output / "vision-hard-examples",
                proposal_mode=proposal_mode)
        else:
            runtime.perception = PerceptionWorker(
                hard_example_directory=output / "vision-hard-examples",
                scheduler=runtime.agent.brain_scheduler,
                learned_detector=learned_detector,
                live_vision_monitor=live_vision_monitor,
                world3d_proposal_mode=proposal_mode)
    runtime.vision_dataset = runtime.map_marker_dataset = None
    if runtime.runtime_profile.visual:
        from .vision_dataset import AutoLabeledExampleCollector
        from .map_marker_dataset import MapMarkerCropCollector
        runtime.vision_dataset = AutoLabeledExampleCollector(output / "vision-dataset")
        runtime.map_marker_dataset = MapMarkerCropCollector(
            output / "map-marker-dataset"
            if os.environ.get("AIPC_MAP_DATASET", "1").strip().lower()
            not in {"0", "false", "no", "off"} else None)
