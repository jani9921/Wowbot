"""Promotion gate: a success label/command ACK is not a reusable episode."""
import math

POLICY = 'EVIDENCE_MANIFEST_V2'


def _id(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 512


def manifest_ids(episode):
    steps = episode.get('steps', ()) if isinstance(episode, dict) else ()
    if not isinstance(steps, (list, tuple)) or len(steps) > 4096:
        return ()
    ids = []
    for step in steps:
        if not isinstance(step, dict):
            return ()
        row = step.get('payload')
        if step.get('kind') != 'VERIFICATION' or not isinstance(row, dict) or row.get('outcome') != 'SUCCESS':
            continue
        values = row.get('evidence_manifest_ids')
        if not isinstance(values, (list, tuple)) or not values or len(values) > 64:
            return ()
        if any(not isinstance(v, str) or not v.strip() or len(v) > 512 for v in values):
            return ()
        ids.extend(values)
    return tuple(dict.fromkeys(ids)) if len(ids) <= 256 else ()


def _roots(manifest):
    lineage = manifest.get('lineage')
    if (not isinstance(lineage, dict) or lineage.get('correlation_uncertain') is not False
            or lineage.get('lineage_truncated') is not False):
        return set()
    roots = lineage.get('root_observation_ids')
    if (not isinstance(roots, list) or not 0 < len(roots) <= 64
            or any(not isinstance(v, str) or not v.strip() or len(v) > 256 for v in roots)):
        return set()
    return set(roots)


def outcome_roots(episode, manifests):
    observed = {s['payload']['observed_observation_id'] for s in episode['steps']
                if s['kind'] == 'VERIFICATION' and s['payload'].get('outcome') == 'SUCCESS'}
    return set().union(*(_roots(m) for m in manifests.values() if m.get('observation_id') in observed))


def reusable_episode(episode, *, manifests=None):
    if (not isinstance(episode, dict) or episode.get('status') != 'SUCCESS'
            or not isinstance(episode.get('result'), dict) or episode['result'].get('verified') is not True):
        return False, 'goal_result_not_verified'
    steps = episode.get('steps') or ()
    if (not isinstance(steps, (list, tuple)) or len(steps) > 4096
            or any(not isinstance(s, dict) or not isinstance(s.get('payload'), dict) for s in steps)):
        return False, 'malformed_episode_steps'
    if any(s.get('kind') in {'MANUAL_BOUNDARY', 'USER_OVERRIDE', 'SESSION_CHANGED'} for s in steps):
        return False, 'episode_has_external_or_session_interruption'
    verified = [s.get('payload') or {} for s in steps if s.get('kind') == 'VERIFICATION'
                and (s.get('payload') or {}).get('outcome') == 'SUCCESS']
    if not verified:
        return False, 'verified_action_evidence_missing'
    for row in verified:
        if (any(not _id(row.get(key)) for key in ('verification_id','action_id',
                                                 'baseline_observation_id','observed_observation_id'))
                or not row.get('evidence')
                or not isinstance(row['evidence'], (list, tuple))
                or len(row['evidence']) > 64 or any(not _id(value) for value in row['evidence'])
                or row['baseline_observation_id'] == row['observed_observation_id']):
            return False, 'unlinked_verification'
    ids = manifest_ids(episode)
    if not ids or not isinstance(manifests, dict) or any(i not in manifests for i in ids):
        return False, 'persisted_evidence_manifest_missing'
    start, end = episode.get('started_at'), episode.get('ended_at')
    if (any(type(t) not in {int, float} or not math.isfinite(t) for t in (start, end)) or start > end):
        return False, 'episode_end_time_unknown'
    initial = episode.get('initial_state') or {}
    if not isinstance(initial, dict) or not _id(episode.get('session')):
        return False, 'episode_identity_unknown'
    for row in verified:
        checked_at = row.get('observed_at')
        if type(checked_at) not in {int, float} or not math.isfinite(checked_at) or not start <= checked_at <= end:
            return False, 'verification_time_outside_episode'
        linked = [manifests[i] for i in row['evidence_manifest_ids']]
        valid = []
        for proof in linked:
            if not isinstance(proof, dict):
                return False, 'evidence_origin_invalid'
            context = proof.get('context') or {}
            if not isinstance(context, dict) or context.get('session_id') != episode.get('session'):
                return False, 'evidence_session_mismatch'
            for key in ('character_guid', 'game_build'):
                if not initial.get(key) or str(context.get(key)) != str(initial[key]):
                    return False, 'evidence_identity_or_build_unknown'
            times = [proof.get(k) for k in ('observed_at', 'received_at', 'expires_at')]
            if (any(type(t) not in {int, float} or not math.isfinite(t) for t in times)
                    or not times[0] <= times[1] <= min(times[2], checked_at) or not _roots(proof)):
                return False, 'evidence_origin_invalid'
            valid.append(proof)
        before = [p for p in valid if p['observation_id'] == row['baseline_observation_id']]
        after = [p for p in valid if p['observation_id'] == row['observed_observation_id']]
        if (not before or not after or not {row['baseline_observation_id'], row['observed_observation_id']}
                .issubset(row['evidence'])):
            return False, 'verification_manifest_unlinked'
        if not any(b['observed_at'] < a['observed_at'] and start <= a['received_at']
                   and not _roots(b) & _roots(a)
                   for b in before for a in after):
            return False, 'verification_reuses_same_source_origin'
    if len(outcome_roots(episode, manifests)) > 256:
        return False, 'episode_origin_budget_exceeded'
    return True, 'persisted_evidence_linked_episode'
