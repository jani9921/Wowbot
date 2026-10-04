"""Bounded crop-only OCR for CPU-first perception.

OCR text is visual evidence.  It never confirms an entity, role, quest state,
or an action by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from PIL import Image, ImageEnhance, ImageFilter

from .models import PixelRect, WorldCandidate


@dataclass(frozen=True, slots=True)
class TextObservation:
    region_id: str
    rect: PixelRect
    text: str
    confidence: float
    engine: str
    observed_at: float
    source: str = "TARGETED_OCR"
    semantic_type: str = "UNKNOWN"


class TesseractCliEngine:
    """Optional local backend; unavailable is an explicit sensor state."""

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("tesseract")

    @property
    def available(self) -> bool:
        return bool(self.executable)

    @property
    def name(self) -> str:
        return "tesseract_cli" if self.available else "unavailable"

    def read(self, image: Image.Image) -> tuple[str, float]:
        if not self.executable:
            return "", 0.0
        # Upscale only the small selected crop. This is deliberately not a
        # full-screen OCR pass.
        gray = image.convert("L")
        gray = ImageEnhance.Contrast(gray).enhance(1.8).filter(ImageFilter.SHARPEN)
        gray = gray.resize((max(1, gray.width * 2), max(1, gray.height * 2)))
        temporary = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        path = Path(temporary.name)
        temporary.close()
        try:
            gray.save(path)
            run = subprocess.run(
                [self.executable, str(path), "stdout", "--psm", "6", "-l", "eng"],
                capture_output=True, text=True, timeout=2.5, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            text = re.sub(r"\s+", " ", run.stdout).strip()[:240]
            useful = sum(char.isalnum() for char in text)
            confidence = min(.88, .35 + useful / 80) if useful >= 2 else 0.0
            return text, confidence
        except (OSError, subprocess.SubprocessError):
            return "", 0.0
        finally:
            path.unlink(missing_ok=True)


class TargetedOCR:
    def __init__(self, engine=None, *, interval: float = .60, max_regions: int = 3,
                 scheduler=None):
        self.engine = engine or TesseractCliEngine()
        self.interval = max(.2, float(interval))
        self.max_regions = max(1, int(max_regions))
        self.scheduler = scheduler
        self.next_at = 0.0
        self.last: tuple[TextObservation, ...] = ()
        self.diagnostics = {"backend": self.engine.name, "available": self.engine.available,
                            "regions": 0, "texts": 0, "status": "idle"}

    @staticmethod
    def _clamp(rect: PixelRect, width: int, height: int) -> PixelRect:
        return PixelRect(max(0, rect.left), max(0, rect.top),
                         min(width, rect.right), min(height, rect.bottom))

    def interest_regions(self, candidates: tuple[WorldCandidate, ...], width: int,
                         height: int, ui_hints: dict | None = None) -> list[tuple[str, PixelRect, float]]:
        hints = ui_hints or {}
        profile = hints.get("world3d_profile") or {}
        profile_name = str(profile.get("name") or "BALANCED").upper()
        ranked = []
        for candidate in candidates:
            if candidate.kind not in {"unknown_subject_candidate", "unknown_subject_probe",
                                      "unknown_symbol_candidate"}:
                continue
            rect = candidate.rect
            # Include overhead/name text and the body top, but keep the crop
            # bounded. This also catches a tooltip when active perception has
            # placed the pointer near the candidate.
            pad_x = min(180, max(28, rect.width * 2))
            pad_y = min(100, max(22, rect.height // 2))
            crop = self._clamp(PixelRect(rect.left-pad_x, rect.top-pad_y,
                                         rect.right+pad_x, rect.bottom), width, height)
            score = candidate.confidence + (.18 if "symbol" in candidate.kind else 0)
            labels = set(candidate.candidate_labels)
            evidence = str(candidate.evidence).lower()
            if profile_name == "COMBAT":
                score += .35 if "nameplate" in evidence or "target" in labels else -.12
                score -= .18 if any("quest" in label for label in labels) else 0.
            elif profile_name == "QUEST_SEARCH":
                score += .34 if ("symbol" in candidate.kind or
                                  any(token in label for label in labels
                                      for token in ("quest", "interact"))) else 0.
            elif profile_name == "NAVIGATION":
                score -= .20  # OCR is subordinate to geometry in this mode.
            ranked.append((f"track:{candidate.track_id or id(candidate)}", crop, score))
        if hints.get("quest_ui_open") or hints.get("gossip_open"):
            ranked.append(("ui:dialog", PixelRect(int(width*.18), int(height*.12),
                                                   int(width*.82), int(height*.88)), 1.2))
        cursor = hints.get("cursor_position") or {}
        nx, ny = cursor.get("nx"), cursor.get("ny")
        if hints.get("tooltip_probe") and isinstance(nx, (int, float)) and isinstance(ny, (int, float)):
            cx, cy = int(float(nx)*width), int((1-float(ny))*height)
            # WoW tooltips can open on either side of the cursor. A bounded
            # foveal crop covers both without OCRing the full screen.
            half_width, half_height = min(220, int(width*.35)), min(150, int(height*.35))
            ranked.append(("ui:cursor_tooltip", self._clamp(
                PixelRect(cx-half_width, cy-half_height,
                          cx+half_width, cy+half_height), width, height), 1.1))
        ranked.sort(key=lambda item: -item[2])
        chosen = []
        max_regions = max(1, int(profile.get("ocr_max_regions") or self.max_regions))
        for item in ranked:
            if item[1].width < 8 or item[1].height < 8:
                continue
            if any(_iou(item[1], old[1]) > .72 for old in chosen):
                continue
            chosen.append(item)
            if len(chosen) >= max_regions:
                break
        return chosen

    def process(self, raw: bytes, width: int, height: int,
                candidates: tuple[WorldCandidate, ...], observed_at: float,
                ui_hints: dict | None = None) -> tuple[TextObservation, ...]:
        profile = (ui_hints or {}).get("world3d_profile") or {}
        interval = max(.2, float(profile.get("ocr_interval_seconds") or self.interval))
        if self.scheduler is not None:
            if not self.scheduler.should_run_ocr(observed_at, interval=interval):
                return self.last
        else:
            if observed_at < self.next_at:
                return self.last
            self.next_at = observed_at + interval
        # Sequential subprocess calls (one Tesseract CLI invocation per
        # region) make this the single most latency-variable step in the
        # whole perception pipeline when the backend is actually available --
        # this duration was previously invisible in vision_diagnostics
        # entirely, folded silently into whichever outer detector/tracker
        # bucket happened to be active that tick.
        started = time.perf_counter()
        regions = self.interest_regions(candidates, width, height, ui_hints)
        if not self.engine.available:
            self.last = ()
            self.diagnostics = {"backend": self.engine.name, "available": False,
                                "regions": len(regions), "texts": 0,
                                "status": "backend_unavailable",
                                "duration_ms": round((time.perf_counter()-started)*1000, 2)}
            return ()
        image = Image.frombytes("RGBA", (width, height), raw, "raw", "BGRA")
        output = []
        for region_id, rect, _ in regions:
            text, confidence = self.engine.read(image.crop((rect.left, rect.top, rect.right, rect.bottom)))
            if text and confidence >= .35:
                output.append(TextObservation(region_id, rect, text, confidence,
                                              self.engine.name, observed_at))
        self.last = tuple(output)
        self.diagnostics = {"backend": self.engine.name, "available": True,
                            "regions": len(regions), "texts": len(output), "status": "ready",
                            "duration_ms": round((time.perf_counter()-started)*1000, 2)}
        return self.last


def _iou(a: PixelRect, b: PixelRect) -> float:
    overlap = max(0, min(a.right, b.right)-max(a.left, b.left)) * \
              max(0, min(a.bottom, b.bottom)-max(a.top, b.top))
    union = a.width*a.height + b.width*b.height - overlap
    return overlap/union if union else 0.0
