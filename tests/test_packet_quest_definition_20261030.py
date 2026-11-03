"""Pinned WPP 12.1 quest-definition records, independent from UI row order."""
from dataclasses import replace
import struct

import pytest

from wowbot.packetio.quest_definition import decode_definition, normalize_definition
from wowbot.packetio.validation import normalize_event, verified_semantics
from test_packet_codecs import decoded
from test_unit_fields_20261027 import bits


def definition_bytes(*, quest_id=58915, objective_id=100040, conditional=True, title='Native test',
                     description='Free the cocoons.', amount=7, weight=1.25, has_data=True):
    data=struct.pack('<i',quest_id)+bytes((0x80 if has_data else 0,))
    if not has_data: return data
    data+=struct.pack('<i',quest_id)
    # Quest type/package/tuning/sort/info/group/follow-up; distinct markers
    # expose offsets accidentally borrowed from an older query layout.
    data+=struct.pack('<7i',2,7,10,-1,5,3,58916)
    data+=struct.pack('<ifii fi',3,1.25,123,4,1.5,50)
    data+=struct.pack('<I',1)       # display spell count
    data+=struct.pack('<ii f ii f i',1001,1,1.0,2,3,1.0,1)
    data+=struct.pack('<i4I',98765,8,16,32,64)
    data+=bytes((0x1b,0x2c,0x3d,0x04))*(16+18+12+20+1+8+3)
    data+=struct.pack('<qIQ',900,2,0x8000000000000001)
    data+=struct.pack('<IIiiiiIIII',1,1,9,33,44,190740,int(conditional),int(conditional),1,1)
    data+=struct.pack('<iii',2001,99,2)  # display spell/player-condition/type
    for order in range(2):
        text=(description if order==0 else '').encode('utf-8')
        data+=struct.pack('<iIbiiiIIfii',objective_id+order,2,9 if order==0 else -1,
                          301000+order,amount,0,16,32,weight,1,0)
        data+=struct.pack('<i',123456)  # visual effect
        data+=bits([(len(text),8),(int(order==0),1)])+text
    data+=struct.pack('<ii',1234,5678)   # treasure and non-displayable treasure
    if conditional:
        for text in (b'Conditional description',b'Conditional completion'):
            data+=struct.pack('<ii',17,190740)+bits([(len(text),12)])+text
    data+=struct.pack('<ii',19,23)       # house room/decor
    strings=[title,'Visible summary','Original quest description','Area description',
             'Giver portrait text','Portrait Giver','Turn-in portrait text','Portrait Finisher','Completion log']
    encoded=[value.encode('utf-8') for value in strings]
    data+=bits([(len(value),width) for value,width in zip(encoded,(9,12,12,9,10,8,10,8,11))]+[(0,1),(0,1)])
    return data+b''.join(encoded)


@pytest.mark.parametrize('build',[69587,70448,70575])
def test_reviewed_query_exports_exact_objective_ids_storage_and_signed_missing_storage(build):
    event=decoded('SMSG_QUERY_QUEST_INFO_RESPONSE',definition_bytes(),build=build)[-1]
    assert event.event_type=='QUEST_DEFINITION'
    assert verified_semantics(normalize_event(event.to_dict()))
    definition=event.payload['definition']
    assert definition['quest_id']==58915 and definition['reward_next_quest_id']==58916
    assert definition['start_item_id']==98765 and definition['giver_creature_id']==190740
    assert definition['flags_ex3']==64 and definition['allowable_races']==0x8000000000000001
    assert definition['title']=='Native test' and definition['has_conditional_texts']
    first,hidden=definition['objectives']
    assert (first['objective_id'],first['storage_index'],first['order'],first['amount'])==(100040,9,0,7)
    assert first['object_id']==301000 and first['progress_bar_weight']==1.25
    assert first['description']=='Free the cocoons.' and first['visible']
    assert hidden['storage_index']==-1 and not hidden['visible']
    assert 'Conditional description' not in str(definition)  # active condition is not known


def test_no_data_response_is_not_an_empty_complete_definition():
    kind,body=decode_definition(definition_bytes(has_data=False))
    assert kind=='QUEST_DEFINITION_UNAVAILABLE' and body=={'quest_id':58915}


def test_utf8_and_wpp_nul_removal_are_bounded_data():
    _,body=decode_definition(definition_bytes(title='Küldetés',description='a\0b'))
    assert body['definition']['title']=='Küldetés'
    assert body['definition']['objectives'][0]['description']=='ab'


@pytest.mark.parametrize('mutation',[
    lambda b:b[:-1], lambda b:b+b'extra',
    lambda b:b[:5]+struct.pack('<i',58916)+b[9:],
])
def test_truncated_extra_or_mismatched_quest_body_never_becomes_a_definition(mutation):
    events=decoded('SMSG_QUERY_QUEST_INFO_RESPONSE',mutation(definition_bytes()))
    assert len(events)==1 and events[0].semantic_status=='UNKNOWN'


def test_wrong_direction_and_nonfinite_weight_fail_closed():
    from wowbot.packetio.pkt import OpcodeManifest, PktEventDecoder, PktV31StreamParser
    from test_packet_codecs import pkt_bytes
    parser=PktV31StreamParser()
    record=parser.feed(pkt_bytes('SMSG_QUERY_QUEST_INFO_RESPONSE',definition_bytes()))[0]
    decoder=PktEventDecoder(selected_pid=77,header=parser.header,manifest=OpcodeManifest.reviewed(69587))
    assert len(decoder.decode_all(replace(record,direction='CLIENT_TO_SERVER')))==1
    assert len(decoded('SMSG_QUERY_QUEST_INFO_RESPONSE',definition_bytes(weight=float('nan'))))==1


def test_unknown_fields_are_not_transported_and_objective_ids_are_unique():
    _,body=decode_definition(definition_bytes())
    source=body['definition']
    assert 'raw_payload' not in normalize_definition({**source,'raw_payload':'not-a-game-field'})
    bad={**source,'objectives':[source['objectives'][0],{**source['objectives'][1],'objective_id':100040}]}
    with pytest.raises(ValueError): normalize_definition(bad)


def test_wire_schema_requires_matching_quest_and_a_reviewed_definition_layout():
    event=decoded('SMSG_QUERY_QUEST_INFO_RESPONSE',definition_bytes())[-1].to_dict()
    event['payload']['quest_id']=58916
    with pytest.raises(ValueError): normalize_event(event)
    event=decoded('SMSG_QUERY_QUEST_INFO_RESPONSE',definition_bytes())[-1].to_dict()
    event['provenance']['payload_layout']='WPP_12_1_REVIEWED_PREFIX_V1'
    assert not verified_semantics(normalize_event(event))
