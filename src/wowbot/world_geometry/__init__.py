"""Read-only world geometry composed from TrinityCore extraction outputs."""

from .service import WorldGeometryService
from .terrain_maps import MapDataSource, TerrainSample, TrinityMapTerrain

__all__ = ["MapDataSource", "TerrainSample", "TrinityMapTerrain", "WorldGeometryService"]
