"""Input-free renderer for World3D debug overlay/replay artifacts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


class World3DDebugRenderer:
    TRACK_COLORS = {
        "ACTIVE": (70, 230, 110, 255),
        "REACQUIRED": (80, 210, 255, 255),
        "TENTATIVE": (255, 210, 70, 255),
        "OCCLUDED": (190, 120, 255, 255),
        "LOST_TEMPORARY": (150, 150, 150, 255),
    }

    @staticmethod
    def _image(frame: tuple[bytes, int, int] | None) -> Image.Image:
        if frame is None:
            raise ValueError("a source frame is required to render an overlay")
        raw, width, height = frame
        if width < 1 or height < 1 or len(raw) != width*height*4:
            raise ValueError("invalid BGRA source frame")
        return Image.frombytes("RGBA", (width, height), raw, "raw", "BGRA")

    def render(self, frame: tuple[bytes, int, int], overlay: dict[str, Any],
               output_path: str | Path) -> Path:
        image = self._image(frame)
        draw = ImageDraw.Draw(image, "RGBA")
        for track in overlay.get("tracks") or ():
            bbox = track.get("bbox") or {}
            if not all(isinstance(bbox.get(key), (int, float))
                       for key in ("left", "top", "right", "bottom")):
                continue
            lifecycle = str(track.get("lifecycle") or "TENTATIVE")
            color = self.TRACK_COLORS.get(lifecycle, (255, 255, 255, 255))
            rect = tuple(int(bbox[key]) for key in ("left", "top", "right", "bottom"))
            draw.rectangle(rect, outline=color, width=2)
            type_label = ((track.get("type_beliefs") or [{}])[0].get("label") or "UNKNOWN")
            role_label = ((track.get("role_beliefs") or [{}])[0].get("label") or "")
            label = (f"{track.get('track_id')} {type_label} {role_label} "
                     f"{float(track.get('confidence', 0.)):.2f}").strip()
            draw.rectangle((rect[0], max(0, rect[1]-13),
                            min(image.width, rect[0]+max(40, len(label)*6)), rect[1]),
                           fill=(0, 0, 0, 180))
            draw.text((rect[0]+2, max(0, rect[1]-12)), label, fill=color)
            motion = (track.get("motion") or {}).get("smoothed_velocity") or {}
            vx, vy = motion.get("x"), motion.get("y")
            if isinstance(vx, (int, float)) and isinstance(vy, (int, float)):
                cx, cy = (rect[0]+rect[2])//2, (rect[1]+rect[3])//2
                draw.line((cx, cy, cx+int(vx*80), cy+int(vy*80)), fill=color, width=2)
        for obstacle in overlay.get("obstacles") or ():
            bbox = obstacle.get("bbox") or {}
            if all(isinstance(bbox.get(key), (int, float))
                   for key in ("left", "top", "right", "bottom")):
                draw.rectangle(tuple(int(bbox[key]) for key in ("left", "top", "right", "bottom")),
                               outline=(255, 70, 70, 230), width=3)
        for entrance in overlay.get("entrances") or ():
            bbox = entrance.get("bbox") or {}
            if all(isinstance(bbox.get(key), (int, float))
                   for key in ("left", "top", "right", "bottom")):
                draw.rectangle(tuple(int(bbox[key]) for key in ("left", "top", "right", "bottom")),
                               outline=(70, 180, 255, 230), width=3)
        sectors = overlay.get("traversability") or ()
        if sectors:
            band_top = max(0, image.height-18)
            width = image.width/max(1, len(sectors))
            for index, sector in enumerate(sectors):
                state = str(sector.get("state") or "UNKNOWN")
                color = ((40, 200, 80, 150) if state == "FREE" else
                         (230, 60, 60, 160) if state in {"BLOCKED", "DANGEROUS"} else
                         (200, 180, 60, 120))
                draw.rectangle((int(index*width), band_top,
                                int((index+1)*width), image.height), fill=color)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG")
        return output

