class MindmapError(Exception):
    """Expected user-facing failure."""


class RouteCollisionError(MindmapError):
    """Two distinct project roots map to the same stable identity."""
