from dataclasses import dataclass


@dataclass(frozen=True)
class AIDifficultyProfile:
    name: str
    speed_scale: float
    lookahead_scale: float
    brake_scale: float
    throttle_scale: float
    drift_target: float
    drift_brake_boost: float
    steering_noise: float
    reaction_delay: float


PROFILES = {
    "easy": AIDifficultyProfile(
        name="easy",
        speed_scale=0.72,
        lookahead_scale=0.80,
        brake_scale=1.35,
        throttle_scale=0.70,
        drift_target=0.15,
        drift_brake_boost=0.10,
        steering_noise=0.08,
        reaction_delay=0.25,
    ),
    "medium": AIDifficultyProfile(
        name="medium",
        speed_scale=0.90,
        lookahead_scale=1.00,
        brake_scale=1.00,
        throttle_scale=0.90,
        drift_target=0.45,
        drift_brake_boost=0.35,
        steering_noise=0.03,
        reaction_delay=0.10,
    ),
    "hard": AIDifficultyProfile(
        name="hard",
        speed_scale=1.05,
        lookahead_scale=1.15,
        brake_scale=0.85,
        throttle_scale=1.00,
        drift_target=0.70,
        drift_brake_boost=0.65,
        steering_noise=0.00,
        reaction_delay=0.00,
    ),
}


def get_profile(level: str) -> AIDifficultyProfile:
    return PROFILES.get(level, PROFILES["medium"])