import random, string, math # global
import config.const as const  # local


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def rand_code(n: int = const.JOIN_CODE_LEN) -> str:
    return "".join(random.choice(const.ROOM_ALPHABET) for _ in range(n))


def rand_name() -> str:
    return "Player" + "".join(random.choice(string.digits) for _ in range(4))


def car_local_to_world(cx: float, cy: float, angle: float, lx: float, ly: float) -> tuple[float, float]:
    """Convert a local (lx, ly) point on the car to world coords."""
    ca, sa = math.cos(angle), math.sin(angle)
    return (cx + lx * ca - ly * sa, cy + lx * sa + ly * ca)
