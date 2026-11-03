"""Applied local progress witness. This is not a game-state provider."""
from collections import deque
import math

from wowbot.context_contracts import context_matches
from wowbot.packetio.delivery import stamp
from wowbot.packetio.stream_progress import normalize
from .models import Observation, json_copy


def token(provider):
    return (provider.process.generation,provider.capture_epoch,provider.continuity_generation)


def observation(event,context,provider,expected,previous):
    return Observation.create({'session_id':context['session_id'],'timestamp':event['timestamp'],
        'frame_id':'progress:'+event['event_id'],'packet_context':context,'progress_control':event,
        'expected_collection_events':list(expected),'previous_progress_sequence':previous,
        'provider_token':list(token(provider)),
        'provenance':{'producer':'RuntimePacketSource','selected_pid':context['selected_pid']}},
        event['received_at_monotonic'],'PACKET_PROGRESS')


def note_collection(model, safe, obs):
    """Called only after own GUID/world/build verification and actual reduction."""
    event=obs.payload.get('packet_event') or {}
    if event.get('delivery_state')=='CONTIGUOUS' and event.get('delivery_stream'):
        model.__dict__.setdefault('_packet_collection_applied',deque(maxlen=2048)).append(safe['event_id'])


def apply(model,obs,*,defer_rebuild=False):
    provider=getattr(model,'session_context_provider',None)
    if provider is None:return False
    from .world_packet_reducer import _context
    from .packet_continuity import refresh
    try:
        event=obs.payload['progress_control']
        value=normalize(event['payload'])
        expected=_context(model,model.addon_state,value['selected_pid'])
        context=obs.payload['packet_context']
        delivery=stamp(event['delivery_stream'])
        sampled=event['sampled_at_monotonic']
        provenance=obs.payload.get('provenance') or {}
        required=obs.payload['expected_collection_events']
        # A UI-map step keeps the transport nonce (world_packet_reducer, 2026-10-31).
        if (expected is None or not context_matches(expected,context,include_ui_map=False)
                or event.get('ipc_context')!=context
                or not context.get('context_id') or obs.session_id!=expected['session_id']
                or provenance.get('producer')!='RuntimePacketSource'
                or provenance.get('selected_pid')!=value['selected_pid']
                or obs.payload['provider_token']!=list(token(provider))
                or value['capture_epoch']!=provider.capture_epoch or value['game_build']!=expected['game_build']
                or value['process_generation']!=provider.process.generation
                or event.get('delivery_state')!='CONTIGUOUS'
                or type(sampled) not in {int,float} or not math.isfinite(sampled)
                or not 0<=obs.received_at-sampled<=2.
                or not isinstance(required,list) or len(required)>1024
                or any(not isinstance(i,str) for i in required)):
            return False
    except (KeyError,ValueError,TypeError,OverflowError):
        return False
    refresh(model,model.state)
    previous=model.__dict__.get('_packet_stream_progress')
    same=bool(previous and previous['context_id']==context['context_id']
              and previous['sender_id']==delivery['sender_id'])
    previous_sequence=previous['delivery_sequence'] if same else 0
    applied=set(model.__dict__.get('_packet_collection_applied',()))
    reason=('progress_chain_unapplied' if obs.payload.get('previous_progress_sequence')!=previous_sequence
            or same and previous['status'] not in {'APPLIED','DECODE_GAP'} else
            'collection_events_unapplied' if not set(required)<=applied else
            'progress_record_regressed' if same and (value['record_number']<=previous['record_number']
                or value['decode_failures']<previous['decode_failures']
                or sampled<previous['sample_time']) else
            # A gap is the witness at which the counter grows (and the fields
            # are discarded below); later witnesses re-cover from there.
            'decode_gap' if value['decode_failures']>(previous['decode_failures'] if same else 0) else 'applied')
    if same and delivery['sequence']<=previous_sequence:
        return False
    # An unread whole UPDATE_OBJECT may hide any own collection change. Keep
    # the fault counter, invalidate current fields, never forward failed bytes.
    if value['decode_failures']>(previous['decode_failures'] if same else 0):
        from .packet_continuity import discard_fields
        discard_fields(model,model.state)
    # Start of the unbroken applied coverage that ends at this witness: every
    # own collection event delivered since then went through the reducer.
    # The first witness of a continuity token covers the whole token (a token
    # change or DECODE_GAP already discarded every older native field); after
    # a DECODE_GAP the coverage restarts at the gap; UNAPPLIED has none.
    if reason!='applied':since=None
    elif previous is None:since=float('-inf')
    elif not same:since=sampled
    elif previous['status']=='APPLIED':since=previous.get('applied_since')
    else:since=previous['sample_time']
    model.__dict__['_packet_stream_progress']={
        'status':'APPLIED' if reason=='applied' else 'DECODE_GAP' if reason=='decode_gap' else 'UNAPPLIED',
        'applied_since':since,
        'reason':reason,'context_id':context['context_id'],'sender_id':delivery['sender_id'],
        'delivery_sequence':delivery['sequence'],'record_number':value['record_number'],
        'decode_failures':value['decode_failures'],'sample_time':sampled,'received_at':obs.received_at,
        'token':token(provider),'collection_events_checked':len(required)}
    if defer_rebuild:model._state_dirty=True
    else:model._rebuild_state()
    return True


WITNESS_AGE=2.


def retained(model,observed_at,now):
    """Lease for one native collection field clock (REV4 P3 retained state).

    The server sends quest-log/inventory VALUES only on change, so a correct
    CREATE baseline went UNKNOWN 2 s later although nothing had changed. The
    fact sampled at ``observed_at`` is still current at ``now`` only while a
    fresh APPLIED witness proves that every own collection event delivered
    since then was applied: an update would have replaced it, an invalidation
    barrier would have removed it, and a token change / DECODE_GAP / record
    gap discards it. No TTL is extended; no input or UI authority follows.
    """
    from .packet_continuity import current
    row=model.__dict__.get('_packet_stream_progress')
    provider=getattr(model,'session_context_provider',None)
    since=(row or {}).get('applied_since')
    return bool(row is not None and provider is not None and row['token']==token(provider) and current(model)
                and row['status']=='APPLIED' and since is not None
                and type(observed_at) in {int,float} and type(now) in {int,float}
                and math.isfinite(observed_at) and math.isfinite(now)
                and since<=observed_at<=row['sample_time'] and 0<=now-row['sample_time']<=WITNESS_AGE)


def view(model,now):
    from .packet_continuity import current
    row=model.__dict__.get('_packet_stream_progress')
    provider=getattr(model,'session_context_provider',None)
    if (row is None or provider is None or row['token']!=token(provider) or not current(model)
            or type(now) not in {int,float} or not math.isfinite(now)):
        return {'status':'UNKNOWN'}
    value=json_copy({key:row[key] for key in ('status','reason','record_number','decode_failures',
                    'sample_time','received_at','collection_events_checked')})
    if not 0<=now-row['sample_time']<=2.:value['status']='EXPIRED'
    return value
