"""Read only login/world/own-public-create layout; never export raw records."""
import collections,json,sys
from pathlib import Path
from wowbot.packetio.pkt import PktV31StreamParser,PktEventDecoder,OpcodeManifest
from wowbot.packetio.update_object import decode_update_object,UpdateLayoutError
from wowbot.packetio.context import same_player

root=Path(r'C:/Users/<user>/Documents/ChatGPT/ai_visual_bot_midnight claude/ai_visual_bot_midnight 1.2/projekt')
path=Path(sys.argv[1])
assert path.resolve().parent==(root/'runtime/ymir/dumps').resolve()
parser=PktV31StreamParser();decoder=None;counts=collections.Counter();proofs=[];logins=[];verifies=[]
with path.open('rb') as source:
    while chunk:=source.read(1024*1024):
        for record in parser.feed(chunk):
            if decoder is None:
                decoder=PktEventDecoder(selected_pid=12912,header=parser.header,
                    manifest=OpcodeManifest.reviewed(parser.header.game_build),
                    process_generation='01dd68847bd94adb')
            name=decoder.manifest.name(record.direction,record.opcode)
            if name in {'CMSG_PLAYER_LOGIN','SMSG_LOGIN_VERIFY_WORLD'}:
                decoder.decode_all(record)
                (logins if name=='CMSG_PLAYER_LOGIN' else verifies).append({
                    'record':record.record_number,'connection':record.connection_index,'time':record.timestamp})
            if name!='SMSG_UPDATE_OBJECT':continue
            try:rows=decode_update_object(record.payload,{})
            except (ValueError,UpdateLayoutError):counts['layout_unreadable']+=1;continue
            counts['object_records_read']+=1
            for row in rows:
                if row.get('object_type')==7:
                    proofs.append({'record':record.record_number,'connection':record.connection_index,
                        'time':record.timestamp,'object_type':row['object_type'],
                        'this_is_you':row.get('this_is_you'),'map_id':row.get('map_id'),
                        'matches_pending_login':any(same_player(row['guid'],v) for v in decoder._login_guids.values())})
result={'logins':logins,'world_verifications':verifies,'own_public_creates':proofs,'counts':dict(counts),
        'raw_records_exported':False,'auth_or_keys_decoded':False,'private_player_fields_requested':False}
Path(__file__).with_name('login-probe-results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
