"""Single read-only composition boundary for MAPS, VMAPS and MMAPS.

MMAPS remains route authority.  MAPS contributes terrain/liquid evidence and
a ground-layer Z hint.  VMAPS answers one question since 2026-10-06 (Z
resolver): which collision surfaces lie on a vertical line (floors, bridges,
roofs, cave ceilings).  It is not line-of-sight evidence.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

from wowbot.navigation.mmap_navmesh import GRID_SIZE, TrinityMMapNavMesh
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
        # {addon instance: server cosmetic map} (packet_server_map).
        self.server_maps: dict[int, int] = {}
        self.last_diagnostics: dict = {
            "available": True,
            "reason": "geometry_sources_ready",
            "maps_configured": terrain is not None,
            "vmaps_configured": self.vmaps_path is not None,
            "mmaps_configured": navmesh is not None,
            "vmap_query_status": "VERTICAL_SURFACES" if self.vmaps_path else "NOT_CONFIGURED",
        }
        # 2026-10-22: MMAPS asks MAPS/VMAPS how deep a liquid polygon is
        # before admitting it as a shallow ford.
        if isinstance(navmesh, TrinityMMapNavMesh) and (terrain is not None or self.vmaps is not None):
            navmesh.liquid_depth = self.liquid_depth
        if isinstance(navmesh, TrinityMMapNavMesh) and terrain is not None:
            navmesh.terrain_height = self.terrain_height
            navmesh.structure_box = self.structure_box if self.vmaps is not None else None
            navmesh.structure_surface = self.structure_surface if self.vmaps is not None else None

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

    def set_server_map(self, instance_id, server_map) -> None:
        """Route on the server's cosmetic map where its own geometry exists.

        Live 2026-10-27 16:10: inside the narrative Obsidian Citadel (server
        map 2534, addon 2444) the 2444 navmesh led into walls; the agent ran
        back and forth at one waypoint for 40 s.  mmaps holds 16 tiles of
        2534 (with maps/vmaps)."""
        if type(instance_id) is not int:
            return
        if type(server_map) is int and server_map != instance_id and self.navmesh.supports(server_map):
            self.server_maps[instance_id] = server_map
        else:
            self.server_maps.pop(instance_id, None)

    def map_for(self, instance_id, *points) -> int:
        """The map whose geometry answers for these points: the server's
        cosmetic map where it has a navmesh tile for every point, else the
        addon instance (outside the narrative area both maps are the same)."""
        server_map = self.server_maps.get(instance_id)
        source = getattr(self.navmesh, "source", None)
        if server_map is None or source is None:
            return instance_id
        for point in points:
            try:
                x, y = float(point["x"]), float(point["y"])
            except (KeyError, TypeError, ValueError):
                return instance_id
            if not (math.isfinite(x) and math.isfinite(y)):
                return instance_id
            grid_x, grid_y = math.floor(32. - x / GRID_SIZE), math.floor(32. - y / GRID_SIZE)
            if not source.exists(f"{server_map:04d}_{grid_x:02d}_{grid_y:02d}.mmtile"):
                return instance_id
        return server_map

    def terrain_sample(self, instance_id: int, point: dict):
        if self.terrain is None:
            return None
        try:
            return self.terrain.sample(self.map_for(instance_id, point), float(point["x"]), float(point["y"]))
        except (KeyError, TypeError, ValueError):
            return None

    # TrinityCore GridMap: a liquid level at or below this is "no liquid".
    INVALID_LIQUID_Z = -1500.
    FLOOR_ABOVE_SURFACE_YARDS = .3
    FLOOR_PROBE_YARDS = 3.
    # Terrain this little above a liquid's surface is its bank (a polygon
    # vertex on the shore).  A cave's lava lies far below the hill's terrain.
    BANK_YARDS = 4.

    def liquid_depth(self, instance_id: int, x: float, y: float, surface_z: float, *,
                     enough: float | None = None, slow: bool = True) -> float | None:
        """Yards from a liquid surface down to the floor under it, or None.

        ADT liquid over ADT ground is exact from MAPS alone (live 2026-10-22:
        the wading player's Z equalled MAPS terrain_z).  A WMO/M2 liquid (a
        cave's lava) or a terrain hole takes the highest VMAPS collision
        surface just below the liquid.  No floor evidence means unknown.
        ``enough``: a MAPS floor at most this deep is answer enough; a VMAPS
        surface could only raise the floor (~3 ms per ray, 2026-10-22).
        ``slow=False``: NaN instead of asking VMAPS (the caller defers).
        """
        sample = None
        if self.terrain is not None:
            try:
                sample = self.terrain.sample(int(instance_id), float(x), float(y))
            except (TypeError, ValueError, OSError):
                sample = None
        terrain = (sample.terrain_z if sample is not None and sample.terrain_z is not None
                   and not sample.is_hole else None)
        liquid = (sample.liquid_z if sample is not None and sample.liquid_flags
                  and sample.liquid_z is not None and sample.liquid_z > self.INVALID_LIQUID_Z else None)
        # GridMap: ground above the liquid level means no liquid here (bank).
        if terrain is not None and liquid is not None and abs(liquid - surface_z) <= 1.:
            return max(0., liquid - terrain)
        top = surface_z + self.FLOOR_ABOVE_SURFACE_YARDS
        if terrain is not None and top < terrain <= surface_z + self.BANK_YARDS:
            return 0.
        floors = [terrain] if terrain is not None and terrain <= top else []
        if floors and enough is not None and surface_z - floors[0] <= enough:
            return max(0., surface_z - floors[0])
        if self.vmaps is not None:
            if not slow:
                return math.nan
            try:
                floors += [height for height in self.vmaps.surfaces_above(
                    int(instance_id), float(x), float(y), surface_z - self.FLOOR_PROBE_YARDS)
                    if height <= top]
            except (KeyError, TypeError, ValueError, OSError):
                pass
        return max(0., surface_z - max(floors)) if floors else None

    def structure_box(self, instance_id: int, x: float, y: float, z: float) -> bool:
        """A VMAPS model (building, stair, bridge, rock) occupies this point."""
        try:
            return self.vmaps.inside_spawn_box(int(instance_id), float(x), float(y), float(z))
        except (KeyError, TypeError, ValueError, OSError):
            return False

    def structure_surface(self, instance_id: int, x: float, y: float, z: float) -> bool:
        """A VMAPS model surface lies within 1 yd of this height (short ray)."""
        try:
            return bool(self.vmaps.surfaces_at(int(instance_id), float(x), float(y),
                                               top=float(z)+1., bottom=float(z)-1.))
        except (KeyError, TypeError, ValueError, OSError):
            return False

    def terrain_height(self, instance_id: int, x: float, y: float) -> tuple[float | None, bool]:
        """(MAPS terrain Z or None, is a terrain hole) at one world X/Y."""
        if self.terrain is None:
            return None, False
        try:
            sample = self.terrain.sample(int(instance_id), float(x), float(y))
        except (TypeError, ValueError, OSError):
            return None, False
        if sample is None:
            return None, False
        return (None if sample.is_hole else sample.terrain_z), bool(sample.is_hole)

    def project_position(self, instance_id: int, point: dict, *, z_hint=None):
        instance_id = self.map_for(instance_id, point)
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
        return finder(self.map_for(instance_id, point), point, radius) if callable(finder) else []

    def vmap_surfaces_at(self, instance_id: int, point: dict) -> list[float]:
        """Every VMAP collision surface height under/over one X/Y, highest first."""
        if self.vmaps is None:
            return []
        try:
            return self.vmaps.surfaces_at(int(self.map_for(instance_id, point)), float(point["x"]),
                                          float(point["y"]))
        except (KeyError, TypeError, ValueError, OSError):
            return []

    def walkable_heights_at(self, instance_id: int, point: dict, radius: float = 2.5) -> list[float]:
        finder = getattr(self.navmesh, "walkable_heights_at", None)
        return finder(self.map_for(instance_id, point), point, radius) if callable(finder) else []

    def walkable_layers_at(self, instance_id: int, point: dict, radius: float = 2.5) -> list[dict]:
        finder = getattr(self.navmesh, "walkable_layers_at", None)
        return finder(self.map_for(instance_id, point), point, radius) if callable(finder) else []

    def find_path(self, instance_id: int, start: dict, destination: dict):
        instance_id = self.map_for(instance_id, start, destination)
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

    def query_path(self, instance_id: int, start: dict, destination: dict):
        from wowbot.geometry_contracts import query_path
        # This facade's legacy method already owns terrain/map adaptation.
        result = query_path(self, instance_id, start, destination, allow_typed=False)
        from dataclasses import replace
        return replace(result, provider="WorldGeometryService", world_map_id=self.map_for(instance_id, start, destination))

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
