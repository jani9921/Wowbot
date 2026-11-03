"""Build a small verified power-unit reference from an existing DB2 export."""
import argparse
import json
from pathlib import Path

from build_client_catalog import sha256, source_metadata


def build(source, definition, decoded, output):
    source, definition, decoded, output = map(Path, (source, definition, decoded, output))
    with decoded.open(encoding='utf-8-sig') as stream:
        manifest = json.loads(next(stream))
        rows = [json.loads(line) for line in stream]
    if (manifest.get('name') != 'PowerType' or manifest.get('source_sha256') != sha256(source)
            or manifest.get('definition_sha256') != sha256(definition)
            or manifest.get('layout_hash') != source_metadata(source).get('layout_hash')
            or len(rows) != manifest.get('row_count')):
        raise ValueError('power reference source/export provenance mismatch')
    profiles, seen = [], set()
    for row in rows:
        value = row['values']
        kind, divisor = value['PowerTypeEnum'], value['DisplayModifier']
        if (row.get('type') != 'row' or row.get('table') != 'PowerType'
                or type(kind) is not int or not 0 <= kind <= 255 or kind in seen
                or type(divisor) is not int or not 0 < divisor <= 100_000
                or type(value['MinPower']) is not int):
            raise ValueError('invalid power reference row')
        seen.add(kind)
        profiles.append({'id': row['id'], 'power_type': kind, 'display_modifier': divisor,
                         'minimum_raw': value['MinPower'], 'token': value['NameGlobalStringTag']})
    result = {'schema': 'aipc.power-reference.v1', 'source_sha256': manifest['source_sha256'],
              'definition_sha256': manifest['definition_sha256'], 'layout_hash': manifest['layout_hash'],
              'schema_label': source_metadata(source).get('schema_label'),
              'live_build_verified': False, 'rows': sorted(profiles, key=lambda p: p['power_type'])}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    return len(profiles)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('source', 'definition', 'decoded', 'output'):
        parser.add_argument('--'+flag, required=True)
    args = parser.parse_args()
    print(json.dumps({'power_types': build(args.source, args.definition, args.decoded, args.output)}))
