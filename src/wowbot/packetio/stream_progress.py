"""Allowlisted local decoder progress; never a server/gameplay observation."""
import hashlib
import json
import math
import re
import time

SCHEMA = 'aipc.packet-progress.v1'
COLLECTION_EVENTS = frozenset({'OWN_QUEST_LOG_UPDATE','OWN_QUEST_LOG_INVALIDATED',
    'OWN_INVENTORY_ROOTS','OWN_INVENTORY_INVALIDATED','OWN_ITEM_UPDATE','OWN_ITEM_REMOVED'})


def normalize(value):
    keys = {'schema','selected_pid','timestamp','capture_epoch','process_generation',
            'game_build','record_number','decode_failures'}
    if not isinstance(value,dict) or set(value)!=keys or value.get('schema')!=SCHEMA:
        raise ValueError('invalid decoder progress shape')
    from .builds import opcode_family
    for key,minimum in (('selected_pid',1),('game_build',1),('record_number',0),('decode_failures',0)):
        if type(value.get(key)) is not int or not minimum <= value[key] < 2**63:
            raise ValueError('invalid decoder progress integer')
    if opcode_family(value['game_build']) is None:
        raise ValueError('unreviewed progress build')
    if (not isinstance(value['capture_epoch'],str) or re.fullmatch('[a-f0-9]{32}',value['capture_epoch']) is None
            or not isinstance(value['process_generation'],str)
            or re.fullmatch('[a-fA-F0-9]{1,32}',value['process_generation']) is None
            or type(value['timestamp']) not in {int,float} or not math.isfinite(value['timestamp'])
            or value['timestamp'] <= 0):
        raise ValueError('invalid decoder progress scope/time')
    return dict(value)


def inbox_record(value):
    value=normalize(value)
    identity=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
    return {'schema':SCHEMA,'event_id':identity,'event_type':'SOURCE_PROGRESS','semantic_status':'CONTROL',
            'timestamp':value['timestamp'],'selected_pid':value['selected_pid'],'payload':value}


class CaptureProgress:
    """Progress only after actual records on a verified own world connection.

    Calling a timer with no record cannot advance this witness. Record time is
    preserved even while following a backlog; no current wall-time restamp.
    """
    def __init__(self, *, clock=time.monotonic, interval=.5):
        self.clock,self.interval=clock,interval
        self.last_record=None
        self.record_gaps=0
        self.next_send=0.

    def note(self, record, decoder):
        if self.last_record is not None and record.record_number != self.last_record+1:
            self.record_gaps+=1
        self.last_record=record.record_number
        if (decoder.process_generation is None
                or record.connection_index not in decoder._verified_player_guids
                or record.direction not in {'SERVER_TO_CLIENT','CLIENT_TO_SERVER'}):
            return None
        now=self.clock()
        if now < self.next_send:return None
        self.next_send=now+self.interval
        return normalize({'schema':SCHEMA,'selected_pid':decoder.selected_pid,'timestamp':record.timestamp,
            'capture_epoch':decoder.capture_epoch,'process_generation':decoder.process_generation,
            'game_build':decoder.header.game_build,'record_number':record.record_number,
            'decode_failures':decoder.collection_decode_failures+self.record_gaps})
