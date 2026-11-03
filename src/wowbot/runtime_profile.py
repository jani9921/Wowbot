"""Composition choice, independent of temporary packet stream health."""
from enum import StrEnum
import os


class RuntimeProfile(StrEnum):
    SERVER = "SERVER"
    LEGACY_VISION = "LEGACY_VISION"

    @property
    def visual(self):
        return self is RuntimeProfile.LEGACY_VISION

    @classmethod
    def resolve(cls, explicit=None):
        if explicit is not None:
            return cls(explicit)
        configured = os.environ.get('AIPC_RUNTIME_PROFILE')
        if configured is not None:
            return cls(configured.strip().upper())
        if os.environ.get('AIPC_SERVER_MODE', '').lower() in {'0', 'false', 'off'}:
            return cls.LEGACY_VISION
        if (os.environ.get('AIPC_SERVER_MODE') is not None
                or os.environ.get('AIPC_PACKET_TELEMETRY', '').lower() in {'1', 'true', 'on', 'yes'}):
            return cls.SERVER
        return cls.LEGACY_VISION
