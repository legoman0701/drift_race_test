"""
High-level engine audio mixer for the AE86 4A-GE Bluetop.

Mixes two BeamNG-style blend layers:
- Intake (engine bay / induction) using soundConfig parameters from JBEAM
- Exhaust (tailpipe) using soundConfigExhaust parameters from JBEAM

Uses authentic BeamNG load calculation and gain mixing:
- Load-based mixing between on/off throttle using maxLoadMix and minLoadMix
- Proper gain scaling with mainGain, onLoadGain, offLoadGain
- EQ filtering with low/high shelf and parametric EQ
"""

try:
    import pygame_ce as pygame  # type: ignore
except Exception:  # pragma: no cover
    import pygame  # type: ignore
import json
import math
import re
import threading
import time
from typing import Optional  # added

# NEW: turbo import
try:
    from drift.audio.turbo_sound import TurboSound  # type: ignore
except Exception:  # pragma: no cover
    TurboSound = None  # type: ignore


def parse_jbeam_file(file_path: str) -> dict:
    """Parse a JBEAM file, handling comments and trailing commas."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Remove C-style comments (// and /* */)
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        # Remove trailing commas before closing braces/brackets
        content = re.sub(r',(\s*[}\]])', r'\1', content)
        
        # Add missing commas between properties (common JBEAM issue)
        # Pattern 1: "] "property" or } "property"
        content = re.sub(r'([\]\}])(\s*)("[\w_]+"\s*:)', r'\1,\2\3', content)
        
        # Pattern 2: } [ (object followed by array)
        content = re.sub(r'(\})(\s*)(\[)', r'\1,\2\3', content)
        
        # Pattern 3: ] [ (array followed by array)
        content = re.sub(r'(\])(\s*)(\[)', r'\1,\2\3', content)
        
        # Pattern 4: } { (object followed by object) 
        content = re.sub(r'(\})(\s*)(\{)', r'\1,\2\3', content)
        
        # Remove extra commas that might have been added
        content = re.sub(r',,+', ',', content)
        
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"Warning: Could not parse JBEAM file {file_path}: {e}")
        # Try to provide more context about the error
        lines = content.split('\n')
        if hasattr(e, 'lineno') and e.lineno <= len(lines):
            print(f"Problem line {e.lineno}: {lines[e.lineno-1].strip()}")
            # Show some context around the error
            start_line = max(1, e.lineno - 2)
            end_line = min(len(lines), e.lineno + 2)
            print("Context:")
            for i in range(start_line, end_line + 1):
                marker = " >> " if i == e.lineno else "    "
                print(f"{marker}Line {i}: {lines[i-1].rstrip()}")
        return {}
    except Exception as e:
        print(f"Warning: Could not read JBEAM file {file_path}: {e}")
        return {}


def db_to_linear(db: float) -> float:
    """Convert decibel value to linear gain multiplier."""
    try:
        return 10.0 ** (db / 20.0)
    except Exception:
        return 1.0


def calculate_load_mix(throttle: float, max_load_mix: float, min_load_mix: float) -> float:
    """Calculate BeamNG-style load mix factor."""
    # Load mix interpolates between minLoadMix (coast) and maxLoadMix (full throttle)
    return min_load_mix + (max_load_mix - min_load_mix) * throttle


class JBeamSoundConfig:
    """JBEAM soundConfig/soundConfigExhaust parameters."""
    
    def __init__(self, config_data: dict):
        # Basic parameters
        self.sample_name = config_data.get("sampleName", "")
        self.intake_muffling = config_data.get("intakeMuffling", 1.0)
        
        # Gain parameters (dB)
        self.main_gain = config_data.get("mainGain", 0.0)
        self.on_load_gain = config_data.get("onLoadGain", 1.0)
        self.off_load_gain = config_data.get("offLoadGain", 0.4)
        
        # Load mixing
        self.max_load_mix = config_data.get("maxLoadMix", 0.8)
        self.min_load_mix = config_data.get("minLoadMix", 0.0)
        
        # EQ parameters (dB and Hz)
        self.low_shelf_gain = config_data.get("lowShelfGain", 0.0)
        self.low_shelf_freq = config_data.get("lowShelfFreq", 80.0)
        self.high_shelf_gain = config_data.get("highShelfGain", 0.0)
        self.high_shelf_freq = config_data.get("highShelfFreq", 2500.0)
        
        self.eq_low_gain = config_data.get("eqLowGain", 0.0)
        self.eq_low_freq = config_data.get("eqLowFreq", 500.0)
        self.eq_low_width = config_data.get("eqLowWidth", 0.1)
        
        self.eq_high_gain = config_data.get("eqHighGain", 0.0)
        self.eq_high_freq = config_data.get("eqHighFreq", 2500.0)
        self.eq_high_width = config_data.get("eqHighWidth", 0.2)
        
        # Fundamental frequency EQ
        self.fundamental_freq_cylinder_count = config_data.get("fundamentalFrequencyCylinderCount", 4)
        self.eq_fundamental_gain = config_data.get("eqFundamentalGain", 0.0)
        
        # Pre-calculate linear gains
        self.main_gain_linear = db_to_linear(self.main_gain)
        self.on_load_gain_linear = self.on_load_gain  # These are already linear multipliers
        self.off_load_gain_linear = self.off_load_gain


class AudioController(threading.Thread):
    """Separate thread for audio processing at fixed rate independent of game FPS."""
    
    def __init__(self, engine_audio, update_rate: float = 100.0):
        """Initialize audio controller thread.
        
        Args:
            engine_audio: EngineAudio instance to control
            update_rate: Updates per second (Hz) for audio processing
        """
        super().__init__(daemon=True)
        self.engine_audio = engine_audio
        self.update_interval = 1.0 / update_rate
        self._running = False
        self._state_lock = threading.Lock()
        
        # Thread-safe state variables
        self._rpm = 0.0
        self._throttle = 0.0
        self._last_update = time.perf_counter()
        
    def set_engine_state(self, rpm: float, throttle: float):
        """Thread-safe method to update engine state from game thread."""
        with self._state_lock:
            self._rpm = float(rpm)
            self._throttle = float(throttle)
    
    def get_engine_state(self):
        """Thread-safe method to read engine state from audio thread."""
        with self._state_lock:
            return self._rpm, self._throttle
    
    def start_audio_thread(self):
        """Start the audio processing thread."""
        if not self._running:
            self._running = True
            self.start()
            print(f"Audio thread started at {1.0/self.update_interval:.1f} Hz")
    
    def stop_audio_thread(self):
        """Stop the audio processing thread."""
        if self._running:
            self._running = False
            self.join(timeout=1.0)
            print("Audio thread stopped")
    
    def run(self):
        """Main audio thread loop - runs at fixed rate independent of game FPS."""
        last_time = time.perf_counter()
        
        while self._running:
            current_time = time.perf_counter()
            dt = current_time - last_time
            last_time = current_time
            
            # Get current engine state
            rpm, throttle = self.get_engine_state()
            
            # Update audio with fixed timestep
            try:
                self.engine_audio.update(rpm, throttle, dt)
            except Exception as e:
                print(f"Audio thread error: {e}")
            
            # Sleep to maintain target update rate
            elapsed = time.perf_counter() - current_time
            sleep_time = max(0, self.update_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)


class EngineAudio:
    """BeamNG-style engine audio mixer with intake and exhaust layers + optional turbo spool."""

    def __init__(self, engine_json: str = "assets/AE86/sound/sr20det_es.sfxBlend2D.json", 
                 jbeam_file: str = "assets/AE86/sound/bx_sr20det_engine.jbeam",
                 exhaust_json: str = None,
                 # --- Master volumes ---
                 engine_master_volume: float = 0.1,
                 turbo_master_volume: float = 0.2,
                 # --- Turbo parameters ---
                 turbo_wav: str = "assets/AE86/sound/turbo_03.wav",
                 turbo_min_pitch: float = 0.5,
                 turbo_max_pitch: float = 2.5,
                 turbo_volume: float = 0.5,
                 turbo_spool_rate: float = 2.5,  # how fast spool rises per second toward target
                 turbo_decay_rate: float = 1.2,  # how fast spool falls per second when off throttle
                 turbo_target_rpm: float = 8000.0,  # rpm at which turbo pitch reaches max
                 enable_turbo: bool = True,
                 # --- Blow-off valve (BOV) parameters ---
                 bov_wav: str = "assets/AE86/sound/turbo_bov.wav",
                 bov_volume: float = 0.7,
                 bov_min_spool: float = 0.25,   # minimum internal spool to allow BOV
                 bov_min_throttle_drop: float = 0.35,  # required drop between last throttle and current
                 bov_cooldown: float = 0.35,     # seconds minimal gap between BOV plays
                 bov_spool_activation: float = 0.6,  # NEW: minimum spool (0-1) for BOV to even consider
                 bov_volume_curve: float = 0.85,  # NEW: exponent shaping for volume scaling vs spool
                 enable_bov: bool = True,
                 ):
        
        # Load sound samples for intake
        engine_data = json.load(open(engine_json))
        intake_audio_path = engine_data["samples"]
        
        # Load JBEAM configuration
        jbeam_data = parse_jbeam_file(jbeam_file)
        
        # Look for soundConfig in the root or in the first engine section
        sound_config = jbeam_data.get("soundConfig", {})
        sound_config_exhaust = jbeam_data.get("soundConfigExhaust", {})
        
        # If not found at root, look in the first engine configuration
        if not sound_config and not sound_config_exhaust:
            for key, value in jbeam_data.items():
                if isinstance(value, dict) and ("engine" in key.lower() or "soundConfig" in value):
                    sound_config = value.get("soundConfig", sound_config)
                    sound_config_exhaust = value.get("soundConfigExhaust", sound_config_exhaust)
                    if sound_config or sound_config_exhaust:
                        break
        
        self.intake_config = JBeamSoundConfig(sound_config)
        self.exhaust_config = JBeamSoundConfig(sound_config_exhaust)
        
        # Load exhaust samples if provided, otherwise use intake samples for both
        if exhaust_json and exhaust_json != engine_json:
            try:
                exhaust_data = json.load(open(exhaust_json))
                exhaust_audio_path = exhaust_data["samples"]
            except:
                print(f"Warning: Could not load exhaust samples from {exhaust_json}, using intake samples")
                exhaust_audio_path = intake_audio_path
        else:
            exhaust_audio_path = intake_audio_path
        
        # Calculate total sounds needed for mixer channels
        total_intake_sounds = len(intake_audio_path[0]) + len(intake_audio_path[1])
        total_exhaust_sounds = len(exhaust_audio_path[0]) + len(exhaust_audio_path[1])
        total_sounds = total_intake_sounds + total_exhaust_sounds
        
        current_channels = pygame.mixer.get_num_channels()
        if current_channels < total_sounds + 8:  # +8 for safety margin
            pygame.mixer.set_num_channels(total_sounds + 8)
            print(f"Increased mixer channels from {current_channels} to {total_sounds + 8}")
        
        # Initialize intake sound layers
        self.intake_off = []
        for audio_off in intake_audio_path[0]:
            sound_off = pygame.mixer.Sound(audio_off[0])
            self.intake_off.append([sound_off, audio_off[1]])
            sound_off.play(loops=-1)
            sound_off.set_volume(0)
        
        self.intake_on = []
        for audio_on in intake_audio_path[1]:
            sound_on = pygame.mixer.Sound(audio_on[0])
            self.intake_on.append([sound_on, audio_on[1]])
            sound_on.play(loops=-1)
            sound_on.set_volume(0)
        
        # Initialize exhaust sound layers
        self.exhaust_off = []
        for audio_off in exhaust_audio_path[0]:
            sound_off = pygame.mixer.Sound(audio_off[0])
            self.exhaust_off.append([sound_off, audio_off[1]])
            sound_off.play(loops=-1)
            sound_off.set_volume(0)
        
        self.exhaust_on = []
        for audio_on in exhaust_audio_path[1]:
            sound_on = pygame.mixer.Sound(audio_on[0])
            self.exhaust_on.append([sound_on, audio_on[1]])
            sound_on.play(loops=-1)
            sound_on.set_volume(0)
        
        print(f"Loaded intake: {len(self.intake_off)} off-throttle, {len(self.intake_on)} on-throttle sounds")
        print(f"Loaded exhaust: {len(self.exhaust_off)} off-throttle, {len(self.exhaust_on)} on-throttle sounds")
        print(f"Intake config: mainGain={self.intake_config.main_gain}dB, loadMix={self.intake_config.min_load_mix}-{self.intake_config.max_load_mix}")
        print(f"Exhaust config: mainGain={self.exhaust_config.main_gain}dB, loadMix={self.exhaust_config.min_load_mix}-{self.exhaust_config.max_load_mix}")
        
        # --- Limiter / headroom settings ---
        self.master_headroom = 0.85  # target max combined volume (mix of many loops)
        self.master_scale = 1.0      # dynamic scale updated each frame
        self.limiter_attack = 10.0   # how fast to reduce (gain units per second toward needed scale)
        self.limiter_release = 1.5   # how fast to recover toward 1.0 when below threshold
        self.enable_debug_limiter = False
        # Master volumes (independent global multipliers)
        self.engine_master_volume = max(0.0, min(2.0, float(engine_master_volume)))
        self.turbo_master_volume = max(0.0, min(2.0, float(turbo_master_volume)))

        # --- Turbo setup ---
        # Store turbo instance (no strict type annotation here to avoid runtime issues in some environments)
        self.turbo = None  # type: ignore
        self.turbo_enabled = False
        self._turbo_spool = 0.0  # 0..1 internal spool ratio
        if enable_turbo and turbo_wav and TurboSound is not None:
            try:
                self.turbo = TurboSound(turbo_wav, min_pitch=turbo_min_pitch, max_pitch=turbo_max_pitch)
                self.turbo_enabled = True
                print(f"Turbo sound initialized from {turbo_wav}")
            except Exception as e:  # pragma: no cover
                print(f"Warning: Turbo sound disabled ({e})")
        # store turbo params regardless
        self._turbo_cfg = {
            "volume": turbo_volume,
            "spool_rate": turbo_spool_rate,
            "decay_rate": turbo_decay_rate,
            "target_rpm": turbo_target_rpm,
            "min_pitch": turbo_min_pitch,
            "max_pitch": turbo_max_pitch,
        }

        # --- BOV setup ---
        self._bov_cfg = {
            "path": bov_wav,
            "volume": max(0.0, min(1.0, bov_volume)),
            "min_spool": max(0.0, min(1.0, bov_min_spool)),
            "spool_activation": max(0.0, min(1.0, bov_spool_activation)),
            "min_drop": max(0.0, min(1.0, bov_min_throttle_drop)),
            "cooldown": max(0.0, bov_cooldown),
            "enabled": bool(enable_bov),
            "vol_curve": max(0.05, bov_volume_curve),
        }
        self._bov_sound = None
        self._bov_time_since = 999.0  # allow immediate trigger
        self._last_throttle = 0.0
        if self._bov_cfg["enabled"]:
            try:
                self._bov_sound = pygame.mixer.Sound(self._bov_cfg["path"])
                self._bov_sound.set_volume(self._bov_cfg["volume"])
                print(f"BOV sound loaded from {self._bov_cfg['path']}")
            except Exception as e:  # pragma: no cover
                print(f"Warning: Could not load BOV sound: {e}")
                self._bov_cfg["enabled"] = False

        # --- Audio thread setup ---
        self._audio_controller = None
        self._threaded_mode = False

    def start_audio_thread(self, update_rate: float = 100.0):
        """Start audio processing in a separate thread at fixed rate.
        
        Args:
            update_rate: Updates per second (Hz) for audio processing
        """
        if self._audio_controller is None:
            self._audio_controller = AudioController(self, update_rate)
            self._audio_controller.start_audio_thread()
            self._threaded_mode = True
            print("Audio thread mode enabled")
        else:
            print("Audio thread already running")

    def stop_audio_thread(self):
        """Stop the audio processing thread."""
        if self._audio_controller is not None:
            self._audio_controller.stop_audio_thread()
            self._audio_controller = None
            self._threaded_mode = False
            print("Audio thread mode disabled")

    def set_engine_state(self, rpm: float, throttle: float):
        """Update engine state. Use this instead of update() when using audio thread."""
        if self._threaded_mode and self._audio_controller:
            self._audio_controller.set_engine_state(rpm, throttle)
        else:
            print("Warning: set_engine_state() called but audio thread not running")

    def enable_turbo(self, enabled: bool = True):
        if enabled and self.turbo and not self.turbo_enabled:
            self.turbo_enabled = True
            print("Turbo sound enabled")
        elif not enabled and self.turbo_enabled:
            if self.turbo:
                self.turbo.stop()
            self.turbo_enabled = False
            print("Turbo sound disabled")

    def update(self, rpm: float, throttle: float, dt: float) -> None:
        """Update engine audio and optional turbo spool."""
        # Clamp inputs
        throttle = max(0.0, min(1.0, throttle))
        rpm = max(0, rpm)
        dt = max(1e-5, dt)

        # --- 1. Compute target linear gains per layer (pre-normalization) ---
        intake_load_mix = calculate_load_mix(throttle, self.intake_config.max_load_mix, self.intake_config.min_load_mix)
        exhaust_load_mix = calculate_load_mix(throttle, self.exhaust_config.max_load_mix, self.exhaust_config.min_load_mix)

        intake_on_gain = intake_load_mix * self.intake_config.on_load_gain_linear * self.intake_config.main_gain_linear * self.intake_config.intake_muffling
        intake_off_gain = (1.0 - intake_load_mix) * self.intake_config.off_load_gain_linear * self.intake_config.main_gain_linear * self.intake_config.intake_muffling
        exhaust_on_gain = exhaust_load_mix * self.exhaust_config.on_load_gain_linear * self.exhaust_config.main_gain_linear
        exhaust_off_gain = (1.0 - exhaust_load_mix) * self.exhaust_config.off_load_gain_linear * self.exhaust_config.main_gain_linear

        # --- 2. Layer pair normalization (on/off pairs) to keep crossfade sum <= 1.0 ---
        def normalize_pair(a: float, b: float, cap: float = 1.0):
            s = a + b
            if s > cap and s > 0.0:
                scale = cap / s
                return a * scale, b * scale
            return a, b

        intake_off_gain, intake_on_gain = normalize_pair(intake_off_gain, intake_on_gain, 1.0)
        exhaust_off_gain, exhaust_on_gain = normalize_pair(exhaust_off_gain, exhaust_on_gain, 1.0)

        # --- 3. Estimate combined mix energy heuristic (sum of active gains) ---
        # We approximate that at most one sample per pair is near peak at a time, but
        # across four lists we can exceed headroom; so sum the larger of each pair.
        est_mix = max(intake_off_gain, intake_on_gain) + max(exhaust_off_gain, exhaust_on_gain)

        # --- 4. Compute required global scale ---
        desired_scale = 1.0
        if est_mix > self.master_headroom and est_mix > 0.0:
            desired_scale = self.master_headroom / est_mix
        
        # Smooth scaling: fast attack (reduce), slow release (increase)
        if desired_scale < self.master_scale:
            # Attack toward smaller value
            delta = self.limiter_attack * dt
            self.master_scale = max(desired_scale, self.master_scale - delta)
        else:
            # Release toward 1.0
            delta = self.limiter_release * dt
            self.master_scale = min(1.0, self.master_scale + delta)

        if self.enable_debug_limiter and self.master_scale < 0.999:
            print(f"[Limiter] est_mix={est_mix:.3f} scale={self.master_scale:.3f}")

        # --- 5. Apply global scale ---
        intake_off_gain *= self.master_scale * self.engine_master_volume
        intake_on_gain *= self.master_scale * self.engine_master_volume
        exhaust_off_gain *= self.master_scale * self.engine_master_volume
        exhaust_on_gain *= self.master_scale * self.engine_master_volume

        # --- 6. Update sound layers ---
        self._update_sound_layer(self.intake_off, rpm, intake_off_gain)
        self._update_sound_layer(self.intake_on, rpm, intake_on_gain)
        self._update_sound_layer(self.exhaust_off, rpm, exhaust_off_gain)
        self._update_sound_layer(self.exhaust_on, rpm, exhaust_on_gain)

        # --- 7. Turbo spool / playback ---
        if self.turbo and self.turbo_enabled:
            # target spool is based on throttle and rpm fraction
            rpm_ratio = min(1.0, rpm / max(100.0, self._turbo_cfg["target_rpm"]))
            target = throttle * rpm_ratio
            if target > self._turbo_spool:
                self._turbo_spool = min(1.0, self._turbo_spool + self._turbo_cfg["spool_rate"] * dt * (target - self._turbo_spool + 0.2))
            else:
                self._turbo_spool = max(0.0, self._turbo_spool - self._turbo_cfg["decay_rate"] * dt * (self._turbo_spool - target + 0.05))
            pitch_span = self._turbo_cfg["max_pitch"] - self._turbo_cfg["min_pitch"]
            pitch = self._turbo_cfg["min_pitch"] + pitch_span * (self._turbo_spool ** 0.65)  # mild easing
            turbo_vol = self._turbo_cfg["volume"] * (0.3 + 0.7 * self._turbo_spool)
            turbo_vol *= self.turbo_master_volume
            self.turbo.play(pitch, volume=turbo_vol)
        elif self.turbo and not self.turbo_enabled:
            self.turbo.stop()

        # --- 8. BOV logic (trigger on rapid throttle lift if spool high) ---
        if self._bov_cfg["enabled"] and self._bov_sound:
            self._bov_time_since += dt
            drop = self._last_throttle - throttle
            if (drop >= self._bov_cfg["min_drop"] and
                self._turbo_spool >= self._bov_cfg["spool_activation"] and
                throttle < 0.2 and  # ensure mostly closed
                self._bov_time_since >= self._bov_cfg["cooldown"]):
                # play one-shot
                try:
                    self._bov_sound.stop()  # ensure retrigger crisp
                    self._bov_sound.set_volume(self._compute_bov_volume())
                    self._bov_sound.play()
                except Exception:
                    pass
                self._bov_time_since = 0.0
        self._last_throttle = throttle

    def stop_all(self):
        """Stop all looping sounds (engine layers + turbo) and audio thread."""
        # Stop audio thread first
        self.stop_audio_thread()
        
        # Stop all sound layers
        for layer in (self.intake_off, self.intake_on, self.exhaust_off, self.exhaust_on):
            for snd, _ in layer:
                try:
                    snd.stop()
                except Exception:
                    pass
        if self.turbo:
            self.turbo.stop()

    def _update_sound_layer(self, sound_layer, rpm: float, gain_multiplier: float):
        """Update a sound layer (on or off throttle) based on RPM with BeamNG-style mixing."""
        if not sound_layer:
            return
            
        # Find the two closest RPM samples for interpolation
        lower_idx = 0
        upper_idx = 0
        
        for i, (sound, sample_rpm) in enumerate(sound_layer):
            if rpm <= sample_rpm:
                upper_idx = i
                lower_idx = max(0, i - 1)
                break
            lower_idx = i
            upper_idx = min(len(sound_layer) - 1, i + 1)
        
        # Set all sounds to 0 volume first
        for sound, _ in sound_layer:
            sound.set_volume(0.0)
        
        # If we're exactly at a sample point or at the extremes
        if lower_idx == upper_idx:
            if gain_multiplier > 0.001:  # Lower threshold for better responsiveness
                volume = min(1.0, gain_multiplier)  # Clamp to pygame's max volume
                sound_layer[lower_idx][0].set_volume(volume)
            return
        
        # Interpolate between the two closest samples
        lower_rpm = sound_layer[lower_idx][1]
        upper_rpm = sound_layer[upper_idx][1]
        
        if upper_rpm != lower_rpm:
            # Calculate interpolation factor (0.0 = lower sample, 1.0 = upper sample)
            interpolation_factor = (rpm - lower_rpm) / (upper_rpm - lower_rpm)
            interpolation_factor = max(0.0, min(1.0, interpolation_factor))
            
            # Calculate volumes for crossfading
            lower_volume = (1.0 - interpolation_factor) * gain_multiplier
            upper_volume = interpolation_factor * gain_multiplier
            
            # Apply volumes with clamping
            if lower_volume > 0.001:
                sound_layer[lower_idx][0].set_volume(min(1.0, lower_volume))
            if upper_volume > 0.001:
                sound_layer[upper_idx][0].set_volume(min(1.0, upper_volume))
        else:
            # Fallback: just use the lower sample
            if gain_multiplier > 0.001:
                sound_layer[lower_idx][0].set_volume(min(1.0, gain_multiplier))

    def set_limiter_debug(self, enabled: bool):
        """Enable or disable limiter debug output."""
        self.enable_debug_limiter = enabled
        if enabled:
            print("Limiter debug enabled")
        else:
            print("Limiter debug disabled")

    # ------------------------------------------------------------------
    # BOV controls
    # ------------------------------------------------------------------
    def trigger_bov(self):
        """Manually trigger the BOV sound ignoring throttle logic (obeys cooldown)."""
        if self._bov_cfg.get("enabled") and self._bov_sound and self._bov_time_since >= self._bov_cfg["cooldown"]:
            try:
                self._bov_sound.stop()
                self._bov_sound.set_volume(self._compute_bov_volume())
                self._bov_sound.play()
                self._bov_time_since = 0.0
            except Exception:
                pass

    def set_bov_enabled(self, enabled: bool):
        self._bov_cfg["enabled"] = bool(enabled)

    def set_bov_volume(self, volume: float):
        self._bov_cfg["volume"] = max(0.0, min(1.0, float(volume)))
        if self._bov_sound:
            self._bov_sound.set_volume(self._compute_bov_volume())

    # Internal helper for scaling BOV volume with spool
    def _compute_bov_volume(self) -> float:
        # Normalize spool between activation threshold and 1.0
        act = self._bov_cfg["spool_activation"]
        s = 0.0
        if self._turbo_spool > act:
            span = 1.0 - act
            if span > 1e-6:
                s = (self._turbo_spool - act) / span
            else:
                s = 1.0
        # Shape with exponent (vol_curve <1 -> louder earlier, >1 -> later)
        s = max(0.0, min(1.0, s)) ** self._bov_cfg["vol_curve"]
        base = self._bov_cfg["volume"]
        return base * (0.35 + 0.65 * s) * self.turbo_master_volume

    # ------------------------------------------------------------------
    # Master volume controls
    # ------------------------------------------------------------------
    def set_engine_master_volume(self, volume: float):
        """Set engine (intake+exhaust) master volume multiplier.

        Parameters
        ----------
        volume : float
            0.0 = mute, 1.0 = default nominal, values >1.0 allowed up to 2.0.
        """
        self.engine_master_volume = max(0.0, min(2.0, float(volume)))

    def set_turbo_master_volume(self, volume: float):
        """Set turbo master volume multiplier (applied after internal spool scaling)."""
        self.turbo_master_volume = max(0.0, min(2.0, float(volume)))

    def get_master_volumes(self):
        """Return a dict of current master volumes for UI/debug."""
        return {
            "engine_master_volume": self.engine_master_volume,
            "turbo_master_volume": self.turbo_master_volume,
        }


__all__ = ["EngineAudio", "AudioController", "JBeamSoundConfig", "db_to_linear", "calculate_load_mix", "parse_jbeam_file", "TurboSound"]
