"""AgentMemory visual rejection memory (zero-information hovers, contradictions).

Split out of memory.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import json
from .models import canonical


class MemoryRejectionMixin:
    """Methods of AgentMemory (memory.py); moved verbatim."""

    def record_rejection(self, marker: dict, *, map_id, reason: str, at: float,
                         ttl: float = 86400., evidence_group: str | None = None,
                         hover_quality: float = 1.) -> dict:
        return self.rejection_memory.record(marker, map_id=map_id, reason=reason, at=at,
                                            ttl=ttl, evidence_group=evidence_group,
                                            hover_quality=hover_quality)
        # Legacy implementation retained below temporarily for source-level
        # compatibility archaeology; production returns through the owner.
        from .rejection import rejection_signature
        signature = rejection_signature(marker)
        context = str(map_id if map_id is not None else "UNKNOWN")
        group = str(evidence_group or
                    f"{marker.get('source') or 'UNKNOWN'}:{int(at // 30)}")
        quality = max(0., min(1., float(hover_quality)))
        with self._tx() as db:
            recent = db.execute("""
                SELECT evidence_group,at FROM rejection_trials
                WHERE signature=? AND map_id=? AND outcome='ZERO_INFORMATION'
                ORDER BY at DESC LIMIT 1
            """, (signature, context)).fetchone()
            # Several retries from the same short scene episode are correlated
            # evidence, even when track IDs or frame IDs changed.
            if recent and 0 <= at-float(recent[1]) < 30.:
                group = str(recent[0])
            provenance = canonical({"source": marker.get("source"),
                                    "track_id": marker.get("track_id"),
                                    "detector_kind": marker.get("detector_kind") or marker.get("kind"),
                                    "evidence_group": group, "hover_quality": quality})
            inserted = db.execute("""
                INSERT OR IGNORE INTO rejection_trials
                    (signature,map_id,evidence_group,at,outcome,hover_quality,reason,provenance)
                VALUES (?,?,?,?,?,?,?,?)
            """, (signature, context, group, at, "ZERO_INFORMATION", quality,
                  reason, provenance)).rowcount
            if not inserted:
                return self.rejection_status(marker, map_id=map_id, at=at)
            db.execute("""
                INSERT INTO rejection_memory(signature,map_id,failures,contradictions,
                    first_seen,last_seen,expires_at,reason,provenance)
                VALUES (?,?,1,0,?,?,?,?,?)
                ON CONFLICT(signature,map_id) DO UPDATE SET
                    failures=rejection_memory.failures+1,last_seen=excluded.last_seen,
                    expires_at=excluded.expires_at,reason=excluded.reason,
                    provenance=excluded.provenance
            """, (signature, context, at, at, at+max(0., ttl), reason, provenance))
        self._rejection_cache.pop((signature, context), None)
        return self.rejection_status(marker, map_id=map_id, at=at)

    def record_rejection_contradiction(self, marker: dict, *, map_id, at: float) -> dict:
        return self.rejection_memory.record_contradiction(marker, map_id=map_id, at=at)
        from .rejection import rejection_signature
        signature = rejection_signature(marker)
        context = str(map_id if map_id is not None else "UNKNOWN")
        provenance = canonical({"source": marker.get("source"),
                                "track_id": marker.get("track_id"),
                                "counterevidence": "INSPECTION_PRODUCED_INFORMATION"})
        with self._tx() as db:
            db.execute("""
                INSERT OR IGNORE INTO rejection_trials
                    (signature,map_id,evidence_group,at,outcome,hover_quality,reason,provenance)
                VALUES (?,?,?,?,?,?,?,?)
            """, (signature, context, f"CONTRADICTION:{int(at * 1000)}", at,
                  "INFORMATION_OBSERVED", 1., "contradicting_information_observed",
                  provenance))
            db.execute("""
                INSERT INTO rejection_memory(signature,map_id,failures,contradictions,
                    first_seen,last_seen,expires_at,reason,provenance)
                VALUES (?,?,0,1,?,?,?,?,?)
                ON CONFLICT(signature,map_id) DO UPDATE SET
                    failures=0,contradictions=rejection_memory.contradictions+1,
                    last_seen=excluded.last_seen,expires_at=excluded.expires_at,
                    reason=excluded.reason,provenance=excluded.provenance
            """, (signature, context, at, at, at, "contradicting_information_observed", provenance))
        self._rejection_cache.pop((signature, context), None)
        return self.rejection_status(marker, map_id=map_id, at=at)

    def rejection_status(self, marker: dict, *, map_id, at: float,
                         threshold: int = 3) -> dict:
        return self.rejection_memory.status(marker, map_id=map_id, at=at, threshold=threshold)
        from .rejection import rejection_signature
        signature = rejection_signature(marker)
        context = str(map_id if map_id is not None else "UNKNOWN")
        cached = self._rejection_cache.get((signature, context))
        if cached and at-cached[0] < .5:
            return dict(cached[1])
        with self._ro() as db:
            row = db.execute("""
                SELECT failures,contradictions,first_seen,last_seen,expires_at,reason,provenance
                FROM rejection_memory WHERE signature=? AND map_id=?
            """, (signature, context)).fetchone()
        if not row or row[4] < at:
            result = {"signature": signature, "map_id": map_id, "belief": "UNKNOWN",
                      "confidence": 0., "failures": 0, "independent_trials": 0,
                      "contradictions": row[1] if row else 0}
            self._rejection_cache[(signature, context)] = at, result
            return dict(result)
        failures = int(row[0])
        rejected = failures >= max(1, int(threshold))
        suppressed = not rejected and failures > 0 and 0 <= at-float(row[3]) <= 15.
        result = {"signature": signature, "map_id": map_id,
                "belief": "REJECTED" if rejected else "SUPPRESSED" if suppressed else "CANDIDATE",
                "confidence": (1. if rejected or suppressed
                               else min(.85, failures/max(1, int(threshold)))),
                "failures": failures, "independent_trials": failures,
                "contradictions": int(row[1]),
                "first_seen": row[2], "last_seen": row[3], "expires_at": row[4],
                "suppressed_until": float(row[3])+15. if suppressed else None,
                "reason": row[5], "provenance": json.loads(row[6]) if row[6] else {}}
        self._rejection_cache[(signature, context)] = at, result
        return dict(result)
