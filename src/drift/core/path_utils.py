import math
from typing import Sequence


def is_path_closed(path_poly: Sequence, threshold: float = 80.0) -> bool:
    """Return True when first and last points are close enough to be treated as closed."""
    if not path_poly or len(path_poly) < 3:
        return False

    try:
        sx, sy = float(path_poly[0][0]), float(path_poly[0][1])
        ex, ey = float(path_poly[-1][0]), float(path_poly[-1][1])
    except Exception:
        return False

    return math.hypot(ex - sx, ey - sy) <= threshold
