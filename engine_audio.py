"""
High-level engine audio mixer for the AE86 4A-GE Bluetop.

Mixes two BeamNG-style blend layers:
- Intake (engine bay / induction) using assets/AE86/sound/blends/4agein.sfxBlend2D.json
- Exhaust (tailpipe) using assets/AE86/sound/blends/4ageex.sfxBlend2D.json

Uses EngineSoundBlend for each layer and updates both with the same RPM and load.
Gains are derived from the Bluetop JBEAM soundConfig values (approximate):
- mainGain (dB) -> linear gain multiplier
- onLoadGain/offLoadGain -> mapped to ON (throttle) and OFF (coast) gains

This is intentionally simple: no reverb, spatialization, or afterfire events.
"""
from __future__ import annotations

from typing import Optional, Tuple

try:
    import pygame_ce as pygame  # type: ignore
except Exception:  # pragma: no cover
    import pygame  # type: ignore

from engine_sound_blend import EngineSoundBlend


def db_to_linear(db: float) -> float:
    try:
        return 10.0 ** (db / 20.0)
    except Exception:
        return 1.0


class EngineAudio:
    """Convenience wrapper to run intake + exhaust layers together."""

    def __init__(
        self,
        intake_blend_json: str = "assets/AE86/sound/blends/4agein.sfxBlend2D.json",
        exhaust_blend_json: str = "assets/AE86/sound/blends/4ageex.sfxBlend2D.json",
        # Root path rewriting for BeamNG -> local assets
        intake_root_map: Optional[Tuple[str, str]] = ("art/sound/engine/4agein", "assets/AE86/sound/4agein"),
        exhaust_root_map: Optional[Tuple[str, str]] = ("art/sound/engine/4ageex", "assets/AE86/sound/4ageex"),
        # Gains as per Bluetop config (approx.):
        intake_main_gain_db: float = -17.0,
        intake_on_gain: float = 1.0,
        intake_off_gain: float = 0.4,
        exhaust_main_gain_db: float = -13.0,
        exhaust_on_gain: float = 1.0,
        exhaust_off_gain: float = 0.3,
        vol_slew_per_s: float = 3.0,
    ) -> None:
        # Convert to linear
        in_main = db_to_linear(intake_main_gain_db)
        ex_main = db_to_linear(exhaust_main_gain_db)

        # Construct layers
        self.intake = None
        self.exhaust = None
        try:
            self.intake = EngineSoundBlend(
                intake_blend_json,
                root_map=intake_root_map,
                base_gain=max(0.0, min(1.0, intake_off_gain * in_main)),
                on_gain=max(0.0, min(1.0, intake_on_gain * in_main)),
                vol_slew_per_s=vol_slew_per_s,
            )
        except Exception as e:
            print("[EngineAudio] Intake init failed:", e)
        try:
            self.exhaust = EngineSoundBlend(
                exhaust_blend_json,
                root_map=exhaust_root_map,
                base_gain=max(0.0, min(1.0, exhaust_off_gain * ex_main)),
                on_gain=max(0.0, min(1.0, exhaust_on_gain * ex_main)),
                vol_slew_per_s=vol_slew_per_s,
            )
        except Exception as e:
            print("[EngineAudio] Exhaust init failed:", e)

    def stop(self, fade_ms: int = 200) -> None:
        if self.intake:
            try:
                self.intake.stop(fade_ms)
            except Exception:
                pass
        if self.exhaust:
            try:
                self.exhaust.stop(fade_ms)
            except Exception:
                pass

    def update(self, rpm: float, throttle: float, dt: float) -> None:
        # Clamp inputs
        throttle = max(0.0, min(1.0, throttle))
        if self.intake:
            try:
                self.intake.update(rpm, throttle, dt)
            except Exception:
                pass
        if self.exhaust:
            try:
                self.exhaust.update(rpm, throttle, dt)
            except Exception:
                pass


__all__ = ["EngineAudio"]
