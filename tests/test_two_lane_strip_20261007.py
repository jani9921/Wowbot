"""Two-lane pixel strip (addon 0.9.61, user 2026-10-07).

Live 11:13 (pid 15440): full FAST samples were 1.1-1.5 KB, so the 850-byte
single-strip budget always fell back to a bounded variant (no quest digest,
no UI error), and a STATE page was shown on one rendered frame of four while
the capture kept ~27 of up to 60 frames/s: 3348 pages gave 108 complete
snapshots, the STATE was > 5 s old 69 % of the time.  The strip now runs
along the top with a FAST lane and a STATE lane side by side; each lane is
framed on its own and the STATE lane holds every page for two frames.
"""
import json
from pathlib import Path

import pytest

from adapters.pixel_bridge import _GRID_CACHE, decode_payload_from_bgra, split_lane_payload
from adapters.telemetry_packets import PacketAssembler
from test_agent_transport import lua_runtime
from test_fast_world_position import LIVE_LIKE_FAST
from test_pixel_strip_resolution_profiles import COLORS, frame as legacy_frame
from wowbot.vision.world3d.scene import build_scene_roi

ADDON = Path(__file__).resolve().parents[1] / "addon" / "AIPlayerControllerExport"
WIDTH, HEIGHT = 1600, 829


def _drawing_chunk() -> str:
    """The addon's own strip layout/drawing code, unchanged."""
    lua = (ADDON / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    start = lua.index("-- Strip layout (0.9.61")
    end = lua.index("-- The expensive quest/inventory snapshot remains rate-limited")
    return lua[start:end]


def _strip(width=WIDTH, height=HEIGHT, minimap_left_px=1435):
    lua = lua_runtime()
    lua.execute(f'''
        PIXEL_COLUMNS, PIXEL_CELL_SIZE, PIXEL_MAX_BYTES = 128, 4, 1000
        PIXEL_PALETTE = {{{{0.05,0.05,0.05}},{{1,0.05,0.05}},{{0.05,1,0.05}},{{0.05,0.2,1}}}}
        PIXEL_HEADER = {{3, 1, 2, 4, 3, 4, 2, 1}}
        pixelCells = {{}}
        namespace = ns
        function safeCall(fn, ...) return fn(...) end
        function safeNumber(v, fallback) if type(v) ~= "number" then return fallback or 0 end return v end
        function GetPhysicalScreenSize() return {width}, {height} end
        UIParent = {{}}
        MinimapCluster = {{GetLeft=function() return {minimap_left_px} * 768 / {height} end,
                           GetEffectiveScale=function() return 1 end}}
        frameState = {{}}
        pixelFrame = {{
            CreateTexture=function(self)
                local t = {{}}
                function t:SetSize(w, h) self.w = w end
                function t:SetPoint(_, _, _, x, y) self.x, self.y = x, y end
                function t:SetColorTexture(r, g, b) self.r, self.g, self.b = r, g, b end
                function t:Show() self.shown = true end
                function t:Hide() self.shown = false end
                frameState[#frameState+1] = t
                return t
            end,
            SetSize=function(self, w, h) self.w, self.h = w, h end,
            ClearAllPoints=function() end,
            SetPoint=function(self, _, _, _, x, y) self.x, self.y = x, y end,
        }}
    ''')
    api = lua.execute(_drawing_chunk() + '''
        return {update=updatePixels, layout=layoutPixelFrame,
                get=function() return pixelLayout end}''')
    api.layout()
    return lua, api


def _raster(lua, width=WIDTH, height=HEIGHT) -> bytes:
    scale = height / 768                       # physical pixels per scale-1 unit
    ox, oy = lua.eval("pixelFrame.x") * scale, -lua.eval("pixelFrame.y") * scale
    image = bytearray(width * height * 4)
    for texture in lua.eval("frameState").values():
        if not texture.shown:
            continue
        palette = (0 if texture.r < .5 and texture.g < .5 and texture.b < .5 else
                   1 if texture.r > .5 else 2 if texture.g > .5 else 3)
        left, top = round(ox + texture.x * scale), round(oy - texture.y * scale)
        size = round(texture.w * scale)
        for y in range(top, min(height, top + size)):
            for x in range(left, min(width, left + size)):
                image[(y*width + x)*4:(y*width + x)*4 + 4] = bytes(COLORS[palette])
    return bytes(image)


def _snapshot(lua):
    lua.execute('''data={monotonic_time=1,timestamp=1001,character_guid="Player-1",
        character_name="Mklé",player_present=true,active_quests={{quest_id=55639,
        objectives={{description=string.rep("Thick Cocoon ",400),current=1,required=5}}}},
        actionbar={},events={},inventory={items={}}}
        fast=''' + LIVE_LIKE_FAST)


@pytest.fixture(autouse=True)
def _fresh_geometry_cache():
    _GRID_CACHE.clear()
    yield
    _GRID_CACHE.clear()


def test_layout_spans_the_top_up_to_the_minimap_with_four_pixel_cells():
    lua, api = _strip()
    layout = api.get()
    assert layout.mode == "LANES"
    fast, state = layout.lanes[1].columns, layout.lanes[2].columns
    assert (fast, state) == (224, 129)                       # 12 + 353*4 = 1424 px < 1427
    assert abs(layout.cell * HEIGHT / 768 - 4) < 1e-9        # exactly four physical pixels
    narrow = _strip(1100, 700, minimap_left_px=900)[1].get()
    assert narrow.mode == "LEGACY"


def test_one_frame_carries_a_complete_fast_sample_and_a_state_page():
    lua, api = _strip()
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    payload = decode_payload_from_bgra(_raster(lua), WIDTH, HEIGHT)
    fast, page = split_lane_payload(payload)
    assert "|FAST|" in fast and "|STATE" in page
    body = json.loads(fast.split("|", 6)[6])
    # Even the pathological 1.1 KB tooltip sample keeps motion detail and the
    # quest digest; a normal live-sized sample is sent complete (variant 1).
    assert "falling" in body["movement"] and body["quest_digest"][0]["id"] == 55122
    lua.execute('fast.mouseover.tooltip = "Quartermaster Richter ~ Level 10"; fast.target = nil')
    api.update(lua.eval("data"), lua.eval("fast"))
    fast = split_lane_payload(decode_payload_from_bgra(_raster(lua), WIDTH, HEIGHT))[0]
    body = json.loads(fast.split("|", 6)[6])
    assert body["mouseover"]["tooltip_text"].startswith("Quartermaster Richter")
    assert body["fast_sample_time"] == body["monotonic_time"] and len(fast) > 850


def test_state_pages_are_held_for_two_frames_and_a_snapshot_completes_quickly():
    lua, api = _strip()
    _snapshot(lua)
    assembler, pages, full = PacketAssembler(), [], None
    for tick in range(40):
        api.update(lua.eval("data"), lua.eval("fast"))
        payload = decode_payload_from_bgra(_raster(lua), WIDTH, HEIGHT)
        pages.append(split_lane_payload(payload)[1].split("|", 6)[3])
        result = assembler.feed(payload, float(tick))
        if result is not None and result.get("transport_kind") != "FAST":
            full = (tick, result)
            break
    assert pages[0] == pages[1] and pages[2] == pages[3]     # each page on two frames
    assert full is not None and full[1]["character_name"] == "Mklé"
    # The FAST sample of the same frame is merged into the completed snapshot.
    assert full[1]["mouseover"]["name"] == "Quartermaster Richter"


def test_a_torn_state_lane_keeps_the_fast_packet_of_the_frame():
    lua, api = _strip()
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    image = bytearray(_raster(lua))
    left, top = 12 + (224 + 50)*4, 12 + 6*4                     # one STATE lane body cell
    for y in range(top, top + 4):
        for x in range(left, left + 4):
            image[(y*WIDTH + x)*4:(y*WIDTH + x)*4 + 4] = bytes((128, 128, 128, 255))
    payload = decode_payload_from_bgra(bytes(image), WIDTH, HEIGHT)
    assert payload is not None and len(split_lane_payload(payload)) == 1 and "|FAST|" in payload


def test_the_single_lane_strip_still_decodes():
    packet = 'AIPC5|s|1|0|1|FAST|{"monotonic_time":1}'
    assert decode_payload_from_bgra(legacy_frame(WIDTH, HEIGHT, packet), WIDTH, HEIGHT) == packet


def test_lane_assembly_survives_one_bad_lane():
    assembler = PacketAssembler()
    assembler.feed('AIPC5|s|1|0|1|STATE|{"monotonic_time":1,"character_guid":"Player-1"}', 1)
    frame_payload = ('AIPC5|s|2|0|1|FAST|{"monotonic_time":2,"mouseover":{"name":"Thick Cocoon"}}\n'
                     'AIPC5|s|3|0|2|STATE|not-json-yet')
    result = assembler.feed(frame_payload, 2)
    assert result["transport_kind"] == "FAST" and result["mouseover"]["name"] == "Thick Cocoon"


def test_yolo_masks_the_whole_top_strip_band():
    scene = build_scene_roi(WIDTH, HEIGHT)
    strip = next(rect for rect in scene.hard_excluded_rects if rect.left == 0 and rect.top == 0)
    assert strip.right >= 12 + 353*4 and strip.bottom >= 12 + 128
    small = build_scene_roi(1280, 720)
    strip = next(rect for rect in small.hard_excluded_rects if rect.left == 0 and rect.top == 0)
    assert strip.bottom >= 140
