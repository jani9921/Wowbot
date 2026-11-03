"""Correlate a selected capture's login, world verification and own create.

Realm and instance connections need not have the same sniffer index. A
different connection is accepted only with a complete reviewed own-player
create naming the exact pending login GUID. No auth or private fields here.
"""
from dataclasses import dataclass

from .context import same_player


@dataclass(frozen=True, slots=True)
class WorldBinding:
    character_guid: str
    world_map_id: int
    connection_index: int


class SessionHandshake:
    MAX_AGE = 60.
    MAX_WORLDS = 4

    def __init__(self):
        self.intent = None
        self.worlds = {}

    def begin(self, guid, record):
        self.intent = (guid,record.connection_index,record.record_number,record.timestamp)
        self.worlds.clear()

    def _current(self, record):
        return (self.intent is not None and record.record_number>self.intent[2]
                and 0<=record.timestamp-self.intent[3]<=self.MAX_AGE)

    def verify_world(self, map_id, record):
        if not self._current(record):
            return None
        if record.connection_index==self.intent[1]:
            return self._finish(map_id,record)
        if len(self.worlds)<self.MAX_WORLDS or record.connection_index in self.worlds:
            self.worlds[record.connection_index]=(map_id,record.record_number,record.timestamp)
        return None

    def needs_create(self, record):
        world=self.worlds.get(record.connection_index)
        return bool(self._current(record) and world is not None
                    and record.record_number>world[1] and record.timestamp>=world[2])

    def identify_create(self, rows, record):
        if not self.needs_create(record):
            return None
        world=self.worlds[record.connection_index]
        claims=[r for r in rows if r.get('kind')=='CREATED' and r.get('this_is_you') is True]
        if (len(claims)!=1 or claims[0].get('object_type')!=7
                or claims[0].get('map_id')!=world[0]
                or not same_player(claims[0]['guid'],self.intent[0])):
            return None
        return self._finish(world[0],record)

    def _finish(self, map_id, record):
        result=WorldBinding(self.intent[0],map_id,record.connection_index)
        self.intent=None
        self.worlds.clear()
        return result
