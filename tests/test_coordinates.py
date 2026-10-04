import pytest
from wowbot.agent.coordinates import client_to_screen, physical_pixels


@pytest.mark.parametrize("width,height,left,top", [(1600,900,0,0),(1445,813,60,40),(1920,1080,-1920,0)])
def test_cv_pixel_round_trip(width,height,left,top):
    for px,py in [(0,0),(width-1,height-1),(int(width*.857),int(height*.175))]:
        assert client_to_screen(px/width,1-py/height,width,height,left,top)==(left+px,top+py)


def test_endpoints_and_invalid_coordinates():
    assert client_to_screen(1,0,1600,900,0,0)==(1599,899)
    with pytest.raises(ValueError): client_to_screen(float('nan'),0,1600,900,0,0)


def test_thread_dpi_restored_on_error_and_failure_refuses_work():
    class Setter:
        def __init__(self): self.calls=[]
        def __call__(self,value): self.calls.append(value); return 123
    class API: SetThreadDpiAwarenessContext=Setter()
    api=API()
    with pytest.raises(ValueError):
        with physical_pixels(api): raise ValueError('test')
    assert api.SetThreadDpiAwarenessContext.calls[0].value != 123
    assert api.SetThreadDpiAwarenessContext.calls[1] == 123
    api.SetThreadDpiAwarenessContext = Setter()
    api.SetThreadDpiAwarenessContext.__class__.__call__ = lambda self,value: None
    with pytest.raises(RuntimeError):
        with physical_pixels(api): pytest.fail('must not execute')
