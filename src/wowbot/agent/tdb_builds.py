"""Select the newest available TDB revision of a logical record.

VerifiedBuild is row provenance, not a global minimum build. A negative value
denotes a manually edited parse of that client build in Trinity data. Distinct
spawn GUIDs, model indexes and polygon vertices remain distinct records.
"""
from __future__ import annotations


def build_number(value):
    try:
        return abs(int(value)) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def newest_rows(rows, key):
    """Keep every same-build row within each semantic key, in stable order."""
    values = list(rows)
    newest = {}
    for row in values:
        identity = key(row)
        newest[identity] = max(newest.get(identity, 0), build_number(row.get('VerifiedBuild')))
    return [row for row in values if build_number(row.get('VerifiedBuild')) == newest[key(row)]]
