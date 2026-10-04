from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; SRC=ROOT/'src'
if str(SRC) not in sys.path: sys.path.insert(0,str(SRC))
from wowbot.navigation.path_geometry import PathGeometry,PathVertex
from wowbot.navigation.trace_pair_analysis import compare_geometries, comparison_to_json

def load(path: Path)->PathGeometry:
 d=json.loads(path.read_text(encoding='utf-8'))
 return PathGeometry(d['context_id'],d.get('edge_id'),tuple(PathVertex(float(v['x']),float(v['y']),int(v['source_sample_index']),v.get('turn_angle_deg')) for v in d['vertices']),float(d['length']))

def main()->int:
 ap=argparse.ArgumentParser(description='Compare two recorded route geometries (passive).')
 ap.add_argument('--main',default='runtime/client-1/path_geometry_main.json')
 ap.add_argument('--alternate',default='runtime/client-1/path_geometry_alt.json')
 ap.add_argument('--output',default='runtime/client-1/route_comparison.json')
 ap.add_argument('--threshold',type=float,default=0.025)
 a=ap.parse_args(); c=compare_geometries(load(Path(a.main)),load(Path(a.alternate)),common_threshold=a.threshold)
 out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(comparison_to_json(c),indent=2),encoding='utf-8')
 print(f'[compare] main={c.vertex_counts[0]} vertices len={c.lengths[0]:.5f}')
 print(f'[compare] alternate={c.vertex_counts[1]} vertices len={c.lengths[1]:.5f}')
 print(f'[compare] start_sep={c.start_separation:.5f} end_sep={c.end_separation:.5f}')
 print(f'[compare] common_pairs={len(c.common_vertex_pairs)}')
 print(f'[compare] first_unmatched main={c.divergence_index_main} alternate={c.divergence_index_alt}')
 print(f'[compare] output={out}')
 return 0
if __name__=='__main__': raise SystemExit(main())
