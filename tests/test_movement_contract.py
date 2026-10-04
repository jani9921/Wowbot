from wowbot.navigation.models import MovementIntent, MovementMode
from wowbot.navigation.movement import MovementFeedback
from wowbot.vision.models import WorldPosition


def test_movement_feedback_is_observation_only():
    intent = MovementIntent(MovementMode.WALK, 90.0, WorldPosition(1, 0), 0.05, 'navigate')
    feedback = MovementFeedback(WorldPosition(0.2, 0), 80.0, True)
    assert intent.mode == MovementMode.WALK
    assert feedback.position.x == 0.2
