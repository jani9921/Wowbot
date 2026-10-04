from __future__ import annotations
import numpy as np
from wowbot.vision.adapters.minimap import detect_minimap

def blank(w=300,h=200):
    return np.zeros((h,w,4),dtype=np.uint8)

def test_detects_two_part_quest_giver_glyph():
    img=blank()
    # narrow upper stroke + separated dot, gold
    img[25:31, 276:278, :3] = (0, 150, 235)
    img[33:35, 276:278, :3] = (0, 150, 235)
    obs=detect_minimap(img.tobytes(),300,200,observed_at=1.0)
    q=[m for m in obs.markers if 'exclamation_symbol_like' in m.candidate_labels]
    assert q and q[0].marker_type=='unknown_minimap_marker' and q[0].symbol is None

def test_detects_two_part_question_glyph():
    img=blank()
    # wider upper stroke + separated dot, gold
    img[25:30, 273:281, :3] = (0, 150, 235)
    img[32:34, 276:279, :3] = (0, 150, 235)
    obs=detect_minimap(img.tobytes(),300,200,observed_at=1.0)
    q=[m for m in obs.markers if 'question_symbol_like' in m.candidate_labels]
    assert q and q[0].marker_type=='unknown_minimap_marker' and q[0].symbol is None

def test_single_gold_dot_is_not_quest_symbol():
    img=blank()
    img[30:34, 278:282, :3] = (0, 150, 235)
    obs=detect_minimap(img.tobytes(),300,200,observed_at=1.0)
    assert not any({'exclamation_symbol_like','question_symbol_like'} & set(m.candidate_labels) for m in obs.markers)
