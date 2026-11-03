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

from adapters.pixel_bridge import (_FAST_ONLY_FRAMES, _GRID_CACHE, _LOST_GRID, _VERTICAL_FAST_CACHE,
                                   decode_payload_from_bgra, split_lane_payload)
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
    start = lua.index("-- STATE starts at the client top")
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
        function mockFrame()
          local frame = {{}}
          function frame:CreateTexture()
                local t = {{}}
                t.parent = self
                function t:SetSize(w, h) self.w = w end
                function t:SetPoint(_, _, _, x, y) self.x, self.y = x, y end
                function t:SetColorTexture(r, g, b) self.r, self.g, self.b = r, g, b end
                function t:Show() self.shown = true end
                function t:Hide() self.shown = false end
                frameState[#frameState+1] = t
                return t
          end
          function frame:SetSize(w, h) self.w, self.h = w, h end
          function frame:SetFrameStrata(value) self.strata = value end
          function frame:SetFrameLevel(value) self.level = value end
          function frame:EnableMouse(value) self.mouseEnabled = value end
          function frame:EnableMouseMotion(value) self.mouseMotionEnabled = value end
          function frame:ClearAllPoints() end
          function frame:SetPoint(anchor, _, _, x, y)
              self.anchor, self.x, self.y = anchor, x, y
          end
          function frame:Show() self.shown = true end
          function frame:Hide() self.shown = false end
          return frame
        end
        pixelFrame = mockFrame()
        fastPixelFrame = mockFrame()
    ''')
    api = lua.execute(_drawing_chunk() + '''
        return {update=updatePixels, layout=layoutPixelFrame,
                get=function() return pixelLayout end}''')
    api.layout()
    return lua, api


def _raster(lua, width=WIDTH, height=HEIGHT, quest_tracker=False, tooltip=False) -> bytes:
    scale = height / 768                       # physical pixels per scale-1 unit
    image = bytearray(width * height * 4)
    if quest_tracker:
        for y in range(220, min(height, 600)):
            for x in range(max(0, width - 210), width):
                image[(y*width+x)*4:(y*width+x)*4+4] = bytes((235, 180, 20, 255))
    for texture in lua.eval("frameState").values():
        if not texture.shown or texture.parent.shown is False:
            continue
        parent = texture.parent
        ox = ((width + parent.x * scale - parent.w * scale) if parent.anchor == "TOPRIGHT"
              else parent.x * scale)
        oy = -parent.y * scale
        palette = (0 if texture.r < .5 and texture.g < .5 and texture.b < .5 else
                   1 if texture.r > .5 else 2 if texture.g > .5 else 3)
        left, top = round(ox + texture.x * scale), round(oy - texture.y * scale)
        size = round(texture.w * scale)
        for y in range(top, min(height, top + size)):
            for x in range(left, min(width, left + size)):
                image[(y*width + x)*4:(y*width + x)*4 + 4] = bytes(COLORS[palette])
    # The live tooltip's font regions were ABOVE the FAST textures despite
    # both parents using TOOLTIP strata. Model that independent frame level,
    # rather than always painting every overlay below the telemetry lane.
    if tooltip and (lua.eval("fastPixelFrame.level") or 0) <= 100:
        for y in range(height - 130, height - 90):
            for x in range(width - 150, width - 15):
                image[(y*width+x)*4:(y*width+x)*4+4] = bytes((220, 220, 220, 255))
    return bytes(image)


def _snapshot(lua):
    lua.execute('''data={monotonic_time=1,timestamp=1001,character_guid="Player-1",
        character_name="Mklé",player_present=true,active_quests={{quest_id=55639,
        objectives={{description=string.rep("Thick Cocoon ",400),current=1,required=5}}}},
        actionbar={},events={},inventory={items={}}}
        fast=''' + LIVE_LIKE_FAST)


@pytest.fixture(autouse=True)
def _fresh_geometry_cache():
    for cache in (_GRID_CACHE, _VERTICAL_FAST_CACHE, _LOST_GRID, _FAST_ONLY_FRAMES):
        cache.clear()
    yield
    for cache in (_GRID_CACHE, _VERTICAL_FAST_CACHE, _LOST_GRID, _FAST_ONLY_FRAMES):
        cache.clear()


def test_state_is_flush_thin_and_wide_fast_is_under_minimap():
    lua, api = _strip()
    layout = api.get()
    assert layout.mode == "LANES"
    fast, state = layout.lanes[1].columns, layout.lanes[2].columns
    assert (fast, state) == (64, 384) and layout.lanes[2].rows == 11
    assert abs(layout.cell * HEIGHT / 768 - 3) < 1e-9
    assert abs(layout.fastCell * HEIGHT / 768 - 3) < 1e-9
    assert lua.eval("pixelFrame.x") == 0 and lua.eval("pixelFrame.y") == 0
    assert round(lua.eval("pixelFrame.h") * HEIGHT / 768) == 33
    assert round(lua.eval("pixelFrame.w") * HEIGHT / 768) == 1152
    assert 1152*33 < .57 * 512*132
    assert round(lua.eval("fastPixelFrame.w") * HEIGHT / 768) == 192
    assert round(lua.eval("fastPixelFrame.h") * HEIGHT / 768) == 336
    assert round(-lua.eval("fastPixelFrame.y") * HEIGHT / 768) == 300
    assert round(-lua.eval("fastPixelFrame.x") * HEIGHT / 768) == 8
    narrow = _strip(1100, 600, minimap_left_px=900)[1].get()
    assert narrow.mode == "LEGACY"


def test_screenshot_sized_quest_tracker_does_not_corrupt_fast():
    width, height = 1466, 756
    lua, api = _strip(width, height, minimap_left_px=1310)
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    payload = decode_payload_from_bgra(_raster(lua, width, height, quest_tracker=True), width, height)
    fast, state = split_lane_payload(payload)
    assert "|FAST|" in fast and "|STATE" in state


def test_hover_tooltip_text_cannot_cover_the_fast_lane_or_intercept_the_mouse():
    # Exact client dimensions of the user's second 2026-10-18 test. The
    # saved 0031/0032 images show the corpse tooltip over the FAST colours.
    width, height = 1293, 670
    lua, api = _strip(width, height)
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    payload = decode_payload_from_bgra(_raster(lua, width, height, tooltip=True), width, height)
    assert len(split_lane_payload(payload)) == 2
    assert "|FAST|" in split_lane_payload(payload)[0]
    for name in ("pixelFrame", "fastPixelFrame"):
        assert lua.eval(name + ".strata") == "TOOLTIP"
        assert lua.eval(name + ".level") > 100
        assert lua.eval(name + ".mouseEnabled") is False
        assert lua.eval(name + ".mouseMotionEnabled") is False


@pytest.mark.parametrize("width,height", [(1280, 720), (1366, 768), (1466, 756),
                                          (1600, 829), (1920, 1080), (2560, 1440)])
def test_thin_state_and_vertical_fast_round_trip_across_resolutions(width, height):
    lua, api = _strip(width, height, minimap_left_px=width-220*height/768)
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    payload = decode_payload_from_bgra(_raster(lua, width, height), width, height)
    fast, page = split_lane_payload(payload)
    assert "|FAST|" in fast and "|STATE" in page
    layout = api.get()
    columns, rows = layout.lanes[2].columns, layout.lanes[2].rows
    assert columns <= 384 and columns*rows >= (1024+8)*4
    # The world mask covers the rendered strip but opens the quest pane below it.
    roi = build_scene_roi(width, height)
    strip_mask = next(rect for rect in roi.hard_excluded_rects if rect.left == 0 and rect.top == 0)
    assert strip_mask.right >= columns*3 and strip_mask.bottom >= rows*3
    assert strip_mask.bottom <= 45


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
    left, top = 50*3, 2*3                                      # one STATE lane body cell
    for y in range(top, top + 3):
        for x in range(left, left + 3):
            image[(y*WIDTH + x)*4:(y*WIDTH + x)*4 + 4] = bytes((128, 128, 128, 255))
    payload = decode_payload_from_bgra(bytes(image), WIDTH, HEIGHT)
    assert payload is not None and len(split_lane_payload(payload)) == 1 and "|FAST|" in payload


def test_cached_fast_survives_a_torn_top_header():
    lua, api = _strip()
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    image = bytearray(_raster(lua))
    assert len(split_lane_payload(decode_payload_from_bgra(bytes(image), WIDTH, HEIGHT))) == 2
    for y in range(4):
        for x in range(4):
            image[(y*WIDTH+x)*4:(y*WIDTH+x)*4+4] = bytes((128, 128, 128, 255))
    assert "|FAST|" in decode_payload_from_bgra(bytes(image), WIDTH, HEIGHT)


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


def test_yolo_masks_the_thin_strip_and_exposes_the_world_below_it():
    scene = build_scene_roi(WIDTH, HEIGHT)
    strip = next(rect for rect in scene.hard_excluded_rects if rect.left == 0 and rect.top == 0)
    assert 1152 <= strip.right <= 1164 and 33 <= strip.bottom <= 45
    assert not any(rect.left <= WIDTH//2 <= rect.right and rect.top <= 60 <= rect.bottom
                   for rect in scene.hard_excluded_rects)
    small = build_scene_roi(1280, 720)
    strip = next(rect for rect in small.hard_excluded_rects if rect.left == 0 and rect.top == 0)
    assert strip.bottom <= 45 and strip.right <= 1164
    legacy = build_scene_roi(961, 541)
    strip = next(rect for rect in legacy.hard_excluded_rects if rect.left == 0 and rect.top == 0)
    assert strip.bottom >= 128 and strip.right >= 512


def test_yolo_masks_the_displaced_fast_strip_below_minimap():
    scene = build_scene_roi(1466, 756)
    assert any(rect.left <= 1266 and rect.right >= 1458 and
               rect.top <= 300 and rect.bottom >= 636
               for rect in scene.hard_excluded_rects)




def test_only_changed_bytes_are_repainted_and_every_frame_still_decodes():
    """0.9.63: the strip used to walk every cell of both lanes each 1/60 s
    tick; the client's frame rate (capture, World3D) fell ~42 -> ~32 Hz.
    Now unchanged bytes cost nothing, and shorter/longer frames still decode."""
    lua, api = _strip()
    lua.execute('''
        paints = 0
        local create = pixelFrame.CreateTexture
        for _, frame in ipairs({pixelFrame, fastPixelFrame}) do
            local original = frame.CreateTexture
            function frame:CreateTexture(...)
                local t = original(self, ...)
                local set = t.SetColorTexture
                function t:SetColorTexture(...) paints = paints + 1; return set(self, ...) end
                return t
            end
        end''')
    _snapshot(lua)
    seen = []
    for step, title in enumerate(("Thick Cocoon", "x", "Harpy Totem Harpy Totem Harpy", "y")):
        lua.execute(f'data.monotonic_time = {2 + step}; fast.monotonic_time = {2 + step}; '
                    f'fast.mouseover = {{name = "{title}"}}')
        api.update(lua.eval("data"), lua.eval("fast"))
        fast, _page = split_lane_payload(decode_payload_from_bgra(_raster(lua), WIDTH, HEIGHT))
        seen.append(json.loads(fast.split("|", 6)[6])["mouseover"]["name"])
    assert seen == ["Thick Cocoon", "x", "Harpy Totem Harpy Totem Harpy", "y"]
    lua.execute("paints = 0")
    lua.execute('fast.monotonic_time = 9')
    api.update(lua.eval("data"), lua.eval("fast"))
    first = lua.eval("paints")
    lua.execute("paints = 0")
    api.update(lua.eval("data"), lua.eval("fast"))        # same FAST sample, held page
    assert lua.eval("paints") < first / 4


def test_compressed_state_pages_still_find_the_vertical_fast_lane():
    """Live 2026-10-10 (0.9.63): the 128-column STATE lane carried only
    STATE_Z pages; the decoder looked for the FAST lane under the minimap
    only after a plain STATE page or a >224-column lane: FAST was never read."""
    lua, api = _strip()
    lua.execute('''
        C_EncodingUtil = {
            CompressString = function(text) return string.sub(text, 1, math.floor(#text / 3)) end,
            EncodeBase64 = function(text) return text end,
        }
        Enum = Enum or {}
        Enum.CompressionMethod = Enum.CompressionMethod or {Zlib = 0}''')
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    lanes = split_lane_payload(decode_payload_from_bgra(_raster(lua), WIDTH, HEIGHT))
    kinds = [packet.split("|", 6)[5] for packet in lanes]
    assert "STATE_Z" in kinds and "FAST" in kinds



def test_the_state_strip_is_found_again_after_the_world_map_covered_it():
    """Live 2026-10-10 17:48: OPEN_MAP covered the top STATE strip for one
    second; afterwards only the FAST lane was decoded, the full state stayed
    40+ s old and the agent waited next to the selected Kee-La."""
    lua, api = _strip()
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    image = _raster(lua)
    assert len(split_lane_payload(decode_payload_from_bgra(image, WIDTH, HEIGHT))) == 2
    covered = bytearray(image)
    for y in range(0, 45):
        for x in range(0, 1160):
            covered[(y*WIDTH+x)*4:(y*WIDTH+x)*4+4] = bytes((40, 30, 20, 255))
    for _ in range(3):
        lanes = split_lane_payload(decode_payload_from_bgra(bytes(covered), WIDTH, HEIGHT))
        assert [packet.split("|", 6)[5] for packet in lanes] == ["FAST"]
    lanes = split_lane_payload(decode_payload_from_bgra(image, WIDTH, HEIGHT))
    assert len(lanes) == 2 and any("|STATE" in packet for packet in lanes)


@pytest.mark.parametrize("initial_state_visible", [True, False])
def test_long_fast_only_period_never_replaces_primary_state_geometry(initial_state_visible):
    """A periodic rediscovery must not promote vertical FAST to STATE's cache."""
    width, height = 1345, 697  # the client size of the 2026-10-15 WAIT run
    lua, api = _strip(width, height, minimap_left_px=width-220*height/768)
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    image = _raster(lua, width, height)
    if initial_state_visible:
        assert len(split_lane_payload(decode_payload_from_bgra(image, width, height))) == 2
    covered = bytes(width*60*4) + image[width*60*4:]
    for _ in range(62):
        payload = decode_payload_from_bgra(covered, width, height)
        assert [packet.split("|", 6)[5] for packet in split_lane_payload(payload)] == ["FAST"]
        primary = _GRID_CACHE.get((width, height))
        assert primary is None or primary[1] < 60
    # An existing origin recovers on the very next frame. At startup without
    # STATE, discovery is bounded but must eventually find the returned strip.
    for _ in range(1 if initial_state_visible else 60):
        payload = decode_payload_from_bgra(image, width, height)
        if any("|STATE" in packet for packet in split_lane_payload(payload)):
            break
    assert len(split_lane_payload(payload)) == 2
    assert _GRID_CACHE[(width, height)][1] < 60


def test_old_polluted_primary_fast_cache_is_repaired_without_losing_state_origin():
    width, height = 1345, 697
    lua, api = _strip(width, height, minimap_left_px=width-220*height/768)
    _snapshot(lua)
    api.update(lua.eval("data"), lua.eval("fast"))
    image = _raster(lua, width, height)
    decode_payload_from_bgra(image, width, height)
    _LOST_GRID[(width, height)] = _GRID_CACHE[(width, height)]
    _GRID_CACHE[(width, height)] = _VERTICAL_FAST_CACHE[(width, height)]
    lanes = split_lane_payload(decode_payload_from_bgra(image, width, height))
    assert len(lanes) == 2
    assert _GRID_CACHE[(width, height)] == (0, 0, 3.0)
