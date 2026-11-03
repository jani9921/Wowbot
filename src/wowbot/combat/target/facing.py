"""Pure facing geometry; target/source authorization and input stay outside."""
import math
from collections.abc import Mapping
from wowbot.value_helpers import number


def bearing_error(player, target, orientation):
    if not isinstance(player, Mapping) or not isinstance(target, Mapping):
        return None
    px, py, tx, ty, facing = (number(v) for v in (
        player.get('x'), player.get('y'), target.get('x'), target.get('y'), orientation))
    if None in (px, py, tx, ty, facing) or math.hypot(tx-px, ty-py) < .5:
        return None
    return (math.atan2(ty-py, tx-px)-facing+math.pi) % math.tau-math.pi
