"""Skyriding feedback from the player's own movement packets (offline).

User 2026-10-25 (Skyriding lessons 65118/65120/65133: glide, dive, use
momentum).  The addon cannot read the forward/up speed or the height; the
client sends them in every movement packet (WPP ReadMovementStats1210: the
AdvFlying block).  The user's own 70575 capture (10:00:32-10:00:53) showed a
Skyward Ascent launch (up 44 yd/s), level glides holding the height while the
speed bled, a dive at pitch -1.34 to the 65 yd/s cap and a pull-up trading
speed for height.
"""
import struct

from wowbot.packetio.pkt import MOVE_ADV_FLYING, MOVE_FLYING, _movement_tail


class Cursor:
    def __init__(self, data: bytes):
        self.data, self.at = data, 0

    def take(self, count):
        if self.at + count > len(self.data):
            raise IndexError
        chunk = self.data[self.at:self.at+count]
        self.at += count
        return chunk

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def f32(self):
        return struct.unpack("<f", self.take(4))[0]

    def packed_guid128(self):
        mask_low, mask_high = self.take(1)[0], self.take(1)[0]
        self.take(bin(mask_low).count("1") + bin(mask_high).count("1"))
        return "guid"


def test_the_adv_flying_block_gives_forward_and_up_speed():
    flags = bytes([0x01, 0x00])                    # HasAdvFlying only
    tail = Cursor(struct.pack("<ff", 54.38, 47.9))
    result = _movement_tail(tail, flags)
    assert set(result) == {"forward_velocity", "up_velocity"}
    assert round(result["forward_velocity"], 2) == 54.38 and round(result["up_velocity"], 1) == 47.9


def test_fall_and_inertia_blocks_are_skipped_in_order():
    flags = bytes([0x20 | 0x02 | 0x01, 0x00])      # fall, inertia, adv flying
    body = (struct.pack("<If", 120, -7.95) + bytes([0x80]) + struct.pack("<fff", .5, .8, 12.)
            + struct.pack("<i", 3) + struct.pack("<fff", 0., 0., 1.) + struct.pack("<I", 500)
            + struct.pack("<ff", 14., 1.7))
    result = _movement_tail(Cursor(body), flags)
    assert round(result["fall_z_speed"], 2) == -7.95 and result["fall_xy_speed"] == 12.
    assert round(result["forward_velocity"], 1) == 14. and round(result["up_velocity"], 1) == 1.7


def test_movement_flags_name_skyriding():
    live = 0x624000800000                           # 10:00:32 CMSG_MOVE_SET_ADV_FLY
    assert live & MOVE_ADV_FLYING and not live & MOVE_FLYING
