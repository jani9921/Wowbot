"""Offline replay of allowlisted login/object records; no transport/input/auth decode."""
import collections,json,sys
from pathlib import Path
from wowbot.packetio.pkt import PktV31StreamParser,PktEventDecoder,OpcodeManifest
from wowbot.packetio.validation import verified_semantics
from wowbot.session_context import SessionContextProvider,ProcessIdentity

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
folder=root/'runtime/ymir/dumps'
path=(max(folder.glob('*.pkt'),key=lambda p:p.stat().st_mtime) if sys.argv[1]=='--latest' else Path(sys.argv[1]))
assert path.resolve().parent==folder.resolve()
parser=PktV31StreamParser();decoder=None;counts=collections.Counter();baselines=[]
provider=SessionContextProvider(ProcessIdentity(77,'0000000000000001',70575))
with path.open('rb') as source:
    while chunk:=source.read(1024*1024):
        for record in parser.feed(chunk):
            if decoder is None:
                decoder=PktEventDecoder(selected_pid=77,header=parser.header,
                    manifest=OpcodeManifest.reviewed(parser.header.game_build),process_generation='0000000000000001')
            name=decoder.manifest.name(record.direction,record.opcode)
            if name not in {'CMSG_PLAYER_LOGIN','SMSG_LOGIN_VERIFY_WORLD','SMSG_UPDATE_OBJECT'}:
                continue
            for event in decoder.decode_all(record):
                if event.semantic_status!='CONFIRMED':continue
                counts[event.event_type]+=1
                if event.event_type=='SESSION_BASELINE':
                    baselines.append({'record':record.record_number,'world_connection':record.connection_index,
                      'layout':event.provenance['payload_layout'],'map':event.payload['world_map_id'],
                      'verified_semantics':verified_semantics(event.to_dict()),
                      'provider_accepted':provider.accept_baseline(event.to_dict())})
result={'source_file':path.name,'baselines':baselines,'semantic_counts':dict(counts),
        'provider_state':provider.state.value,'collection_decode_failures':decoder.collection_decode_failures,
        'partial_trailing_record_bytes':parser.buffered_bytes,'raw_payload_exported':False,
        'auth_or_keys_decoded':False,'new_live_acceptance':False}
Path(__file__).with_name('recorded-session-replay-results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
