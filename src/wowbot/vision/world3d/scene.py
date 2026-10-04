from __future__ import annotations

from dataclasses import dataclass

from .models import PixelRect, WorldSceneROI


@dataclass(frozen=True, slots=True)
class WorldSceneProfile:
    """Retail-first playable 3D ROI with conservative HUD exclusion zones."""
    top_excluded_px: int = 92
    # Preserve the thin game title/status strip, but expose the rest of the
    # upper screen to YOLO. Heuristic CV still uses ``top_excluded_px`` and
    # the top band remains listed in ``excluded_rects``.
    learned_top_px: int = 12
    learned_bottom_ratio: float = 1.0
    bottom_excluded_ratio: float = 0.255
    # Keep the playable 3D area wide. Right-side HUD is excluded as explicit
    # overlays below so scene content remains visible to Vision.
    right_excluded_ratio: float = 0.0
    minimap_excluded_width_px: int = 180
    minimap_excluded_bottom_ratio: float = 0.36
    quest_excluded_width_px: int = 240
    quest_excluded_top_ratio: float = 0.34
    quest_excluded_bottom_ratio: float = 0.74
    left_excluded_px: int = 0
    left_hud_width_px: int = 240
    left_hud_width_ratio: float = 0.35
    left_hud_top_ratio: float = 0.53
    addon_hud_width_ratio: float = 0.36
    addon_hud_bottom_ratio: float = 0.18
    player_frame_left_ratio: float = 0.24
    player_frame_right_ratio: float = 0.36
    player_frame_top_ratio: float = 0.67
    player_frame_bottom_ratio: float = 0.77
    target_frame_left_ratio: float = 0.64
    target_frame_right_ratio: float = 0.77
    target_frame_top_ratio: float = 0.68
    target_frame_bottom_ratio: float = 0.77
    learned_right_hud_width_ratio: float = 0.12
    learned_chat_right_ratio: float = 0.25
    learned_chat_top_ratio: float = 0.76
    learned_actionbar_left_ratio: float = 0.30
    learned_actionbar_right_ratio: float = 0.70
    learned_actionbar_top_ratio: float = 0.87
    learned_microbar_left_ratio: float = 0.83
    learned_microbar_top_ratio: float = 0.90
    # In the normal third-person camera the player's own avatar usually occupies
    # this lower-centre band. This is post-detection attention metadata, never
    # a pixel mask: nearby NPCs and symbols may overlap it.
    self_avatar_left_ratio: float = 0.40
    self_avatar_right_ratio: float = 0.60
    self_avatar_top_ratio: float = 0.42
    right_hud_top_ratio: float = 0.0
    right_hud_bottom_ratio: float = 0.38


def build_scene_roi(width: int, height: int, profile: WorldSceneProfile | None = None) -> WorldSceneROI:
    if width < 320 or height < 240:
        raise ValueError("frame is too small for a WoW scene")
    cfg = profile or WorldSceneProfile()
    left = cfg.left_excluded_px
    top = cfg.top_excluded_px
    right = max(left + 1, int(round(width * (1.0 - cfg.right_excluded_ratio))))
    bottom = max(top + 1, int(round(height * (1.0 - cfg.bottom_excluded_ratio))))
    rect = PixelRect(left, top, min(width, right), min(height, bottom))

    excluded: list[PixelRect] = [
        # Top title bar + addon/debug strip visible in the live reference frame.
        PixelRect(0, 0, width, min(height, top)),
        # Bottom action-bar / chat region.
        PixelRect(0, rect.bottom, width, height),
        # Right-side HUD overlays. Keep the scene itself visible to the right
        # of the old ROI; only the minimap and quest tracker bands are masked.
        PixelRect(max(rect.left, width - cfg.minimap_excluded_width_px), 0, width,
                  min(rect.bottom, int(round(height * cfg.minimap_excluded_bottom_ratio)))),
        PixelRect(max(rect.left, width - cfg.quest_excluded_width_px),
                  min(rect.bottom, int(round(height * cfg.quest_excluded_top_ratio))),
                  width, min(rect.bottom, int(round(height * cfg.quest_excluded_bottom_ratio)))),
    ]

    # Left unit frames / chat-adjacent HUD occupy the lower-left corner.
    left_hud_top = int(round(height * cfg.left_hud_top_ratio))
    left_hud_right = min(width, max(cfg.left_hud_width_px,
                                    int(round(width * cfg.left_hud_width_ratio))))
    excluded.append(PixelRect(0, left_hud_top, left_hud_right, rect.bottom))

    # Hard learned-detector masks follow stable Retail/addon UI surfaces from
    # the user-marked live reference layout. The upper middle and unobstructed
    # lower world stay visible; only actual UI islands are removed.
    learned_top = max(0, min(top, int(cfg.learned_top_px)))
    learned_bottom = min(height, max(learned_top + 1, int(round(
        height * cfg.learned_bottom_ratio))))
    addon_hud = PixelRect(
        0, 0, min(width, int(round(width * cfg.addon_hud_width_ratio))),
        min(rect.bottom, int(round(height * cfg.addon_hud_bottom_ratio))))
    player_frame = PixelRect(
        int(round(width * cfg.player_frame_left_ratio)),
        int(round(height * cfg.player_frame_top_ratio)),
        int(round(width * cfg.player_frame_right_ratio)),
        min(learned_bottom, int(round(height * cfg.player_frame_bottom_ratio))))
    target_frame = PixelRect(
        int(round(width * cfg.target_frame_left_ratio)),
        int(round(height * cfg.target_frame_top_ratio)),
        int(round(width * cfg.target_frame_right_ratio)),
        min(learned_bottom, int(round(height * cfg.target_frame_bottom_ratio))))
    right_hud = PixelRect(
        int(round(width * (1.0 - cfg.learned_right_hud_width_ratio))),
        0, width, learned_bottom)
    chat = PixelRect(0, int(round(height * cfg.learned_chat_top_ratio)),
                     int(round(width * cfg.learned_chat_right_ratio)), learned_bottom)
    actionbar = PixelRect(
        int(round(width * cfg.learned_actionbar_left_ratio)),
        int(round(height * cfg.learned_actionbar_top_ratio)),
        int(round(width * cfg.learned_actionbar_right_ratio)), learned_bottom)
    microbar = PixelRect(
        int(round(width * cfg.learned_microbar_left_ratio)),
        int(round(height * cfg.learned_microbar_top_ratio)), width, learned_bottom)
    hard_excluded = (addon_hud, right_hud, chat, actionbar, microbar,
                     player_frame, target_frame)
    excluded.extend((player_frame, target_frame))

    self_top = min(rect.bottom, int(round(height * cfg.self_avatar_top_ratio)))
    self_avatar_rect = PixelRect(
        int(round(width * cfg.self_avatar_left_ratio)), self_top,
        int(round(width * cfg.self_avatar_right_ratio)), rect.bottom)
    learned_rect = PixelRect(rect.left, learned_top, rect.right, learned_bottom)

    # Keep the right-side exclusion explicit as a stable rule for later profiles.
    if cfg.right_hud_top_ratio > 0.0 or cfg.right_hud_bottom_ratio > 0.0:
        rtop = int(round(height * cfg.right_hud_top_ratio))
        rbottom = int(round(height * cfg.right_hud_bottom_ratio))
        excluded.append(PixelRect(rect.right, rtop, width, min(rect.bottom, rbottom)))

    return WorldSceneROI(rect=rect, excluded_rects=tuple(excluded),
                         profile="retail_generic", self_avatar_rect=self_avatar_rect,
                         learned_rect=learned_rect,
                         hard_excluded_rects=hard_excluded)
