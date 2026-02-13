"""Turbo sound system with multiple pre-generated speed variations.

Provides both the legacy single-file system and a new multi-track system
that uses pre-generated speed variations for better audio quality.

Usage examples:

    # Legacy single-file system
    turbo = TurboSound("turbo_03.wav")
    turbo.play(pitch_factor=1.25, volume=0.6)
    
    # New multi-track system
    turbo = MultiTrackTurboSound("turbo_14s_sounds/")
    turbo.play(speed_factor=2.5, volume=0.8)  # Uses turbo_speed_2.5.wav with mixing

Design notes:
* Legacy system quantizes pitch and uses resampling for dynamic pitch changes
* New system uses pre-generated files and mixes between closest speed tracks
* Multi-track system provides better audio quality and performance
* Both systems support seamless looping and volume control
* Mixer init is expected to be done by caller.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os, wave, numpy as np, pygame

__all__ = ["TurboSound", "MultiTrackTurboSound", "load_wav_samples"]


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
        pitch_factor = float(pitch_factor)
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


class MultiTrackTurboSound:
    """Advanced turbo sound system using pre-generated speed variations.
    
    Uses multiple pre-generated audio files at different speeds and mixes
    between them for better audio quality than real-time resampling.
    
    Parameters
    ----------
    sounds_dir : str | Path
        Directory containing turbo_speed_X.X.wav files (e.g., turbo_speed_1.0.wav)
    min_speed, max_speed : float
        Speed range bounds for the turbo system
    speed_decimals : int
        Precision for speed quantization (should match file naming)
    volume_fade_range : float
        Cross-fade range between tracks (0.1 = fade over 0.1 speed units)
    """
    
    def __init__(
        self,
        sounds_dir: str | Path,
        *,
        min_speed: float = 1.0,
        max_speed: float = 5.0,
        speed_decimals: int = 1,
        volume_fade_range: float = 0.1,
    ) -> None:
        self.sounds_dir = Path(sounds_dir)
        self.min_speed = min_speed
        self.max_speed = max_speed
        self.speed_decimals = speed_decimals
        self.volume_fade_range = volume_fade_range
        
        # Load all available speed tracks
        self.speed_tracks = {}
        self.speed_sounds = {}
        self.current_tracks = []  # Currently playing tracks
        
        self._load_speed_tracks()
        
        # Get sorted list of available speeds for interpolation
        self.available_speeds = sorted(self.speed_tracks.keys())
        print(f"MultiTrackTurboSound: Loaded {len(self.available_speeds)} speed tracks")
        print(f"Speed range: {min(self.available_speeds):.1f}x to {max(self.available_speeds):.1f}x")
    
    def _load_speed_tracks(self):
        """Load all turbo_speed_X.X.wav files from the sounds directory."""
        if not self.sounds_dir.exists():
            print(f"Warning: Turbo sounds directory not found: {self.sounds_dir}")
            return
        
        pattern = "turbo_speed_*.wav"
        for wav_file in self.sounds_dir.glob(pattern):
            try:
                # Extract speed from filename: turbo_speed_2.5.wav -> 2.5
                speed_str = wav_file.stem.replace("turbo_speed_", "")
                speed = float(speed_str)
                
                # Load the audio file
                sound = pygame.mixer.Sound(str(wav_file))
                
                self.speed_tracks[speed] = str(wav_file)
                self.speed_sounds[speed] = sound
                
                # print(f"  Loaded: {wav_file.name} -> speed {speed:.1f}x")
                
            except (ValueError, pygame.error) as e:
                print(f"Warning: Could not load {wav_file}: {e}")
    
    def play(self, speed_factor: float, volume: float = 1.0) -> None:
        """Play turbo sound at given speed factor with cross-fading between tracks.
        
        Parameters
        ----------
        speed_factor : float
            Target speed multiplier (1.0 = normal speed, 2.0 = double speed, etc.)
        volume : float
            Master volume (0.0 to 1.0)
        """
        if not self.available_speeds:
            return  # No tracks loaded
        
        speed_factor = max(self.min_speed, min(self.max_speed, speed_factor))
        volume = max(0.0, min(1.0, volume))
        
        # Find the two closest speed tracks for mixing
        lower_speed, upper_speed = self._find_mixing_tracks(speed_factor)
        
        # Stop any tracks that aren't needed
        self._stop_unused_tracks([lower_speed, upper_speed])
        
        if lower_speed == upper_speed:
            # Exact match - play single track
            self._play_single_track(lower_speed, volume)
        else:
            # Mix between two tracks
            self._play_mixed_tracks(lower_speed, upper_speed, speed_factor, volume)
    
    def _find_mixing_tracks(self, target_speed: float) -> tuple[float, float]:
        """Find the two closest speed tracks for the target speed."""
        if target_speed <= self.available_speeds[0]:
            return self.available_speeds[0], self.available_speeds[0]
        if target_speed >= self.available_speeds[-1]:
            return self.available_speeds[-1], self.available_speeds[-1]
        
        # Find surrounding speeds
        for i in range(len(self.available_speeds) - 1):
            if self.available_speeds[i] <= target_speed <= self.available_speeds[i + 1]:
                return self.available_speeds[i], self.available_speeds[i + 1]
        
        # Fallback to closest single track
        closest = min(self.available_speeds, key=lambda x: abs(x - target_speed))
        return closest, closest
    
    def _play_single_track(self, speed: float, volume: float):
        """Play a single speed track."""
        sound = self.speed_sounds[speed]
        
        # Start playing if not already playing
        if speed not in self.current_tracks:
            sound.play(-1)  # Loop indefinitely
            self.current_tracks.append(speed)
        
        sound.set_volume(volume)
    
    def _play_mixed_tracks(self, lower_speed: float, upper_speed: float, target_speed: float, volume: float):
        """Play and mix between two speed tracks."""
        # Calculate mixing ratio
        speed_range = upper_speed - lower_speed
        if speed_range > 0:
            mix_ratio = (target_speed - lower_speed) / speed_range
        else:
            mix_ratio = 0.0
        
        # Calculate volumes with cross-fade
        lower_volume = volume * (1.0 - mix_ratio)
        upper_volume = volume * mix_ratio
        
        # Play both tracks
        for speed, track_volume in [(lower_speed, lower_volume), (upper_speed, upper_volume)]:
            sound = self.speed_sounds[speed]
            
            # Start playing if not already playing
            if speed not in self.current_tracks:
                sound.play(-1)  # Loop indefinitely
                self.current_tracks.append(speed)
            
            sound.set_volume(track_volume)
    
    def _stop_unused_tracks(self, needed_tracks: list[float]):
        """Stop any tracks that aren't needed for current playback."""
        tracks_to_stop = [track for track in self.current_tracks if track not in needed_tracks]
        
        for track in tracks_to_stop:
            self.speed_sounds[track].stop()
            self.current_tracks.remove(track)
    
    def stop(self):
        """Stop all turbo sound playback."""
        for speed in list(self.current_tracks):
            self.speed_sounds[speed].stop()
        self.current_tracks.clear()
    
    def get_info(self) -> dict:
        """Get information about loaded tracks."""
        return {
            "tracks_loaded": len(self.available_speeds),
            "speed_range": (min(self.available_speeds), max(self.available_speeds)) if self.available_speeds else (0, 0),
            "current_tracks": self.current_tracks,
            "sounds_dir": str(self.sounds_dir)
        }

