"""Single read-only composition boundary for MAPS, VMAPS and MMAPS.

MMAPS remains route authority.  MAPS contributes terrain/liquid evidence and
a ground-layer Z hint.  VMAPS answers one question since 2026-10-06 (Z
resolver): which collision surfaces lie on a vertical line (floors, bridges,
roofs, cave ceilings).  It is not line-of-sight evidence.
"""
from __future__ import annotations

import os
from pathlib import Path

from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh
from .terrain_maps import TrinityMapTerrain
from .vmaps import TrinityVMaps


_DEFAULT_RETAIL_ROOT = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_")


class WorldGeometryService:
    def __init__(self, *, navmesh, terrain: TrinityMapTerrain | None = None,
                 vmaps_path: str | Path | None = None):
        self.navmesh = navmesh
        self.terrain = terrain
        self.vmaps_path = Path(vmaps_path).resolve() if vmaps_path else None
        self.vmaps = TrinityVMaps(self.vmaps_path) if self.vmaps_path is not None else None
        self.last_surface_projection: dict = {}
        self.last_diagnostics: dict = {
            "available": True,
            "reason": "geometry_sources_ready",
            "maps_configured": terrain is not None,
            "vmaps_configured": self.vmaps_path is not None,
            "mmaps_configured": navmesh is not None,
            "vmap_query_status": "VERTICAL_SURFACES" if self.vmaps_path else "NOT_CONFIGURED",
        }

    @classmethod
    def from_paths(cls, navmesh_path: str | Path, *, world_data_path: str | Path | None = None):
        configured = os.getenv("WOWBOT_WORLD_DATA_PATH", "").strip()
        root = Path(world_data_path or configured) if (world_data_path or configured) else _DEFAULT_RETAIL_ROOT
        terrain = None
        vmaps = None
        try:
            if (root / "maps").is_dir() or root.name.lower() == "maps":
                terrain = TrinityMapTerrain(root)
        except OSError:
            terrain = None
        data_root = root.parent if root.name.lower() in {"maps", "vmaps"} else root
        candidate_vmaps = data_root / "vmaps"
        if candidate_vmaps.is_dir():
            vmaps = candidate_vmaps
        return cls(navmesh=TrinityMMapNavMesh(navmesh_path), terrain=terrain, vmaps_path=vmaps)

    @classmethod
    def from_environment(cls):
        mmap_path = os.getenv("WOWBOT_MMAP_PATH", "").strip()
        if not mmap_path:
            return None
        try:
            return cls.from_paths(mmap_path)
        except (OSError, ValueError):
            return None

    def close(self) -> None:
        self.navmesh.close()

    def supports(self, instance_id: int) -> bool:
        return self.navmesh.supports(instance_id)

    def terrain_sample(self, instance_id: int, point: dict):
        if self.terrain is None:
            return None
        try:
            return self.terrain.sample(instance_id, float(point["x"]), float(point["y"]))
        except (KeyError, TypeError, ValueError):
            return None

    def project_position(self, instance_id: int, point: dict, *, z_hint=None):
        sample = self.terrain_sample(instance_id, point)
        terrain_hint = (sample.terrain_z
                        if sample is not None and not sample.is_hole and not sample.has_liquid
                        else None)
        effective_hint = z_hint if z_hint is not None else terrain_hint
        projected = self.navmesh.project_position(instance_id, point, z_hint=effective_hint)
        if projected is not None:
            projected = dict(projected)
            projected["terrain_z"] = terrain_hint
            projected["terrain_liquid_z"] = sample.liquid_z if sample is not None else None
            projected["terrain_liquid_flags"] = sample.liquid_flags if sample is not None else 0
            projected["surface_layer_hint_source"] = (
                "ACTIVE_ROUTE" if z_hint is not None else
                "TRINITYCORE_MAPS" if terrain_hint is not None else "NONE")
        self.last_surface_projection = {
            **self.navmesh.last_surface_projection,
            "terrain": sample.to_dict() if sample is not None else None,
            "vmap_query_status": "VERTICAL_SURFACES" if self.vmaps_path else "NOT_CONFIGURED",
        }
        return projected

    def walkable_points_near(self, instance_id: int, point: dict, radius: float) -> list[dict]:
        finder = getattr(self.navmesh, "walkable_points_near", None)
        return finder(instance_id, point, radius) if callable(finder) else []

    def vmap_surfaces_at(self, instance_id: int, point: dict) -> list[float]:
        """Every VMAP collision surface height under/over one X/Y, highest first."""
        if self.vmaps is None:
            return []
        try:
            return self.vmaps.surfaces_at(int(instance_id), float(point["x"]), float(point["y"]))
        except (KeyError, TypeError, ValueError, OSError):
            return []

    def walkable_heights_at(self, instance_id: int, point: dict, radius: float = 2.5) -> list[float]:
        finder = getattr(self.navmesh, "walkable_heights_at", None)
        return finder(instance_id, point, radius) if callable(finder) else []

    def walkable_layers_at(self, instance_id: int, point: dict, radius: float = 2.5) -> list[dict]:
        finder = getattr(self.navmesh, "walkable_layers_at", None)
        return finder(instance_id, point, radius) if callable(finder) else []

    def find_path(self, instance_id: int, start: dict, destination: dict):
        start = self._with_terrain_hint(instance_id, start)
        destination = self._with_terrain_hint(instance_id, destination)
        result = self.navmesh.find_path(instance_id, start, destination)
        self.last_diagnostics = {
            **self.navmesh.last_diagnostics,
            "maps_configured": self.terrain is not None,
            "vmaps_configured": self.vmaps_path is not None,
            "vmap_query_status": "VERTICAL_SURFACES" if self.vmaps_path else "NOT_CONFIGURED",
        }
        return result

    def _with_terrain_hint(self, instance_id: int, point: dict) -> dict:
        if point.get("z_known") is not False and "z" in point:
            return point
        sample = self.terrain_sample(instance_id, point)
        # Liquid-covered terrain is often the floor below a bridge, bank or
        # quest NPC platform.  It is valid environment evidence but not a
        # safe navmesh layer hint.  Leave Z unknown so MMAPS can select the
        # horizontally nearest reachable surface.
        if (sample is None or sample.is_hole or sample.has_liquid
                or sample.terrain_z is None):
            return point
        return {
            **point,
            "z": sample.terrain_z,
            "z_known": True,
            "z_observed": False,
            "z_estimated": True,
            "z_source": "TRINITYCORE_MAPS_TERRAIN",
        }
