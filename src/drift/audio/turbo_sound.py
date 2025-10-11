"""Turbo (or generic pitched loop) sound system.

Provides a small reusable helper for creating a looping sound whose pitch
changes with an input factor (e.g. turbo RPM / boost). Implementation keeps
an LRU cache of resampled variants to avoid constant resample churn.

Usage example:

    turbo = TurboSound("turbo_03.wav")
    turbo.play(pitch_factor=1.25, volume=0.6)
    # In your loop – call play again with updated pitch/volume. It will only
    # rebuild the sound when the quantized pitch changes.

Design notes:
* Quantizes pitch to 2 decimal places (configurable) to bound cache size.
* Resampling uses simple numpy.interp – fast enough for moderate lengths.
* Supports mono or multi-channel WAV; pygame expects int16 arrays.
* Mixer init is expected to be done by caller.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import wave, numpy as np, pygame

__all__ = ["TurboSound", "load_wav_samples"]


def load_wav_samples(path: str | Path):
    """Load a WAV file returning (int16 ndarray[frames, channels], framerate, channels).

    Converts 8-bit unsigned & 32-bit to 16-bit signed as pygame expects.
    """
    path = Path(path)
    with wave.open(str(path), 'rb') as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    dtype_map = {1: np.uint8, 2: np.int16, 4: np.int32}
    if sampwidth not in dtype_map:
        raise ValueError(f"Unsupported sample width: {sampwidth} bytes")
    data = np.frombuffer(raw, dtype=dtype_map[sampwidth])

    if sampwidth == 1:  # unsigned -> signed 16
        data = (data.astype(np.int16) - 128) << 8
    elif sampwidth == 4:  # naive downcast (keep high 16 bits)
        data = (data >> 16).astype(np.int16)
    else:
        data = data.astype(np.int16)

    if channels > 1:
        data = data.reshape(-1, channels)
    else:
        data = data.reshape(-1, 1)
    return data, framerate, channels


class TurboSound:
    """Manage a looping pitched sound with cached resampled variants.

    Parameters
    ----------
    wav_path : str | Path
        Path to base loop sample (should be seamless).
    pitch_decimals : int
        Quantization decimals for pitch cache key.
    min_pitch, max_pitch : float
        Bounds clamp for requested pitch factors.
    cache_size : int
        Maximum distinct pitch variants retained.
    """

    def __init__(
        self,
        wav_path: str | Path,
        *,
        pitch_decimals: int = 2,
        min_pitch: float = 0.25,
        max_pitch: float = 4.0,
        cache_size: int = 64,
    ) -> None:
        self.base_samples, self.sample_rate, self.channels = load_wav_samples(wav_path)
        self.pitch_decimals = pitch_decimals
        self.min_pitch = min_pitch
        self.max_pitch = max_pitch
        self.cache_size = cache_size
        self.current_pitch: float | None = None
        self.current_sound: pygame.mixer.Sound | None = None

        # Build a cached maker. We wrap an lru_cache around a nested function so
        # that cache size can be dynamic per instance.
        @lru_cache(maxsize=cache_size)
        def _make(pitch_key: float):  # pitch_key already quantized
            return self._resample_make_sound(pitch_key)

        self._cached_make = _make  # store for use in play()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def play(self, pitch_factor: float, volume: float = 1.0) -> None:
        """Play/update looping sound at given pitch + volume.

        Only rebuilds/resamples if quantized pitch changes. Safe to call each frame.
        """
        pitch_factor = float(pitch_factor)*0.5
        volume = max(0.0, min(1.0, float(volume)))
        clamped = max(self.min_pitch, min(self.max_pitch, pitch_factor))
        pitch_key = round(clamped, self.pitch_decimals)

        if pitch_key != self.current_pitch:
            # Swap sound
            if self.current_sound:
                self.current_sound.stop()
            snd = self._cached_make(pitch_key)
            snd.set_volume(volume)
            snd.play(-1)
            self.current_sound = snd
            self.current_pitch = pitch_key
        else:
            if self.current_sound:
                self.current_sound.set_volume(volume)

    def stop(self):  # optional helper
        if self.current_sound:
            self.current_sound.stop()
            self.current_sound = None
            self.current_pitch = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _resample_make_sound(self, pitch_factor: float) -> pygame.mixer.Sound:
        """Create a pygame Sound object for the given pitch factor."""
        frames = self.base_samples.shape[0]
        new_len = int(frames / pitch_factor)
        new_len = max(32, new_len)
        idx = np.linspace(0, frames - 1, new_len)

        if self.channels == 1:
            resampled = np.interp(idx, np.arange(frames), self.base_samples[:, 0]).astype(np.int16)
            resampled = resampled.reshape(-1, 1)
        else:
            chans = [
                np.interp(idx, np.arange(frames), self.base_samples[:, c])
                for c in range(self.channels)
            ]
            resampled = np.stack(chans, axis=1).astype(np.int16)
        return pygame.sndarray.make_sound(resampled)

