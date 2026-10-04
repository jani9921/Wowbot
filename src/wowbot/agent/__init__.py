"""Shared goal → world → plan → skill → verify package.

Keep the public ``AutonomousAgent`` convenience export lazy.  Canonical
verification/skill modules import data contracts from ``agent.models`` and
must not pull the full engine back in while those contracts are loading.
"""

__all__ = ["AutonomousAgent"]


def __getattr__(name):
    if name == "AutonomousAgent":
        from .engine import AutonomousAgent
        return AutonomousAgent
    raise AttributeError(name)
