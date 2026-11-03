"""Lazy compatibility exports; structured runtime imports no detector or tracker."""
from importlib import import_module

_EXPORTS = {'MouseoverAssociation': ('.mouseover_association', 'MouseoverAssociation'), 'associate_mouseover': ('.mouseover_association', 'associate_mouseover'), 'LocalEntity': ('.local_world', 'LocalEntity'), 'LocalWorldModel': ('.local_world', 'LocalWorldModel'), 'build_local_world_model': ('.local_world', 'build_local_world_model'), 'OpenCvBackendStatus': ('.opencv_backend', 'OpenCvBackendStatus'), 'OpenCvComputeBackend': ('.opencv_backend', 'OpenCvComputeBackend'), 'create_opencv_backend': ('.opencv_backend', 'create_opencv_backend'), 'MapMouseover': ('.map_mouseover', 'MapMouseover'), 'classify_tooltip': ('.map_mouseover', 'classify_tooltip'), 'normalize_map_mouseover': ('.map_mouseover', 'normalize_map_mouseover'), 'WorldPointMemory': ('.world_point_memory', 'WorldPointMemory')}
__all__ = tuple(_EXPORTS)

def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module, __name__), attribute)
    globals()[name] = value
    return value
