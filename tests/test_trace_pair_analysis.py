from wowbot.navigation.path_geometry import PathGeometry, PathVertex
from wowbot.navigation.trace_pair_analysis import compare_geometries

def test_same_start_two_routes_can_diverge():
    a=PathGeometry('map:1409',None,(PathVertex(0,0,0),PathVertex(0.1,0,1),PathVertex(0.2,0,2)),0.2)
    b=PathGeometry('map:1409',None,(PathVertex(0,0,0),PathVertex(0.1,0.01,1),PathVertex(0.1,0.1,2)),0.2)
    c=compare_geometries(a,b,common_threshold=0.02)
    assert c.start_separation == 0
    assert c.divergence_index_main == 2
    assert c.divergence_index_alt == 2

def test_context_must_match():
    a=PathGeometry('map:1',None,(PathVertex(0,0,0),PathVertex(1,0,1)),1)
    b=PathGeometry('map:2',None,(PathVertex(0,0,0),PathVertex(1,0,1)),1)
    try: compare_geometries(a,b)
    except ValueError: pass
    else: raise AssertionError('expected ValueError')
