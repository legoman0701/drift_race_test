"""
High-level engine audio mixer with separated intake and engine sound systems.

Mixes two distinct audio layers:
- Intake Sound: RPM-based only using soundConfig parameters from JBEAM
  - Uses intakeMuffling and RPM-based sample selection
  - No throttle-based volume modulation (intake is constant at given RPM)
- Engine Sound: RPM + throttle volume-based using soundConfigExhaust parameters from JBEAM  
  - Uses load-based mixing between on/off throttle using maxLoadMix and minLoadMix
  - Throttle affects volume: higher throttle = louder engine sound
  - Proper gain scaling with mainGain, onLoadGain, offLoadGain

Uses authentic BeamNG load calculation and gain mixing with EQ filtering.
"""

import pygame, json, re, os, math
from drift.tools.paths import asset_path, normalize_asset_path
# turbo import
try: from drift.audio.turbo_sound import TurboSound, MultiTrackTurboSound  # type: ignore
except Exception:  # pragma: no cover
    TurboSound = None  # type: ignore
    MultiTrackTurboSound = None  # type: ignore
# gear shift sound import
try: from drift.audio.gear_shift_sound import GearShiftSound  # type: ignore
except Exception:  # pragma: no cover
    GearShiftSound = None  # type: ignore


def parse_jbeam_file(file_path: str) -> dict:
    """Parse a JBEAM file, handling comments and trailing commas."""
    try:
        with open(normalize_asset_path(file_path), 'r', encoding='utf-8') as f:
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


def resolve_audio_path(json_path: str, car_folder = None) -> str:
    """
    Resolve BeamNG-style audio paths to actual file paths.
    
    BeamNG JSON files use paths like "art/sound/engine/4_alt_int/file.wav"
    but actual files are in "assets/cars/ae86/sound/engine/4_alt_int/file.wav"
    """
    # If path is already absolute or relative to current directory, use as-is
    if os.path.exists(json_path):
        return json_path
    
    # If no car folder specified, default to ae86
    if car_folder is None:
        car_folder = asset_path("cars", "ae86", "sound")
    
    # Convert car_folder to string if it's a Path object
    car_folder_str = str(car_folder)
    
    # Convert BeamNG path format to our asset structure
    if json_path.startswith("art/sound/"):
        # art/sound/engine/4_alt_int/file.wav -> assets/cars/ae86/sound/engine/4_alt_int/file.wav
        relative_path = json_path.replace("art/sound/", "")
        resolved_path = os.path.join(car_folder_str, relative_path)
    else:
        # Assume it's already a relative path from the car sound folder
        resolved_path = os.path.join(car_folder_str, json_path)
    
    # Normalize path separators for the current OS
    resolved_path = os.path.normpath(resolved_path)
    
    if not os.path.exists(resolved_path):
        print(f"Warning: Audio file not found: {resolved_path} (original: {json_path})")
    
    return resolved_path


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


def calculate_fundamental_frequency(rpm: float, cylinder_count: int = 4) -> float:
    """Calculate fundamental engine frequency based on RPM and cylinder count."""
    # For 4-stroke engines: frequency = (RPM * cylinder_count) / (60 * 2)
    # Divide by 2 because 4-stroke engines fire once every 2 revolutions per cylinder
    return (rpm * cylinder_count) / 120.0


def apply_eq_gain(base_gain: float, eq_gain_db: float, frequency: float, target_freq: float, width: float = 0.1) -> float:
    """Apply parametric EQ gain based on frequency proximity."""
    if eq_gain_db == 0.0:
        return base_gain
    
    # Calculate frequency ratio (logarithmic)
    if target_freq <= 0 or frequency <= 0:
        return base_gain
    
    freq_ratio = abs(math.log(frequency / target_freq))
    
    # Apply bell curve based on width parameter
    if freq_ratio <= width:
        # Within the EQ band - apply full gain
        eq_factor = db_to_linear(eq_gain_db)
    elif freq_ratio <= width * 3:
        # Transition zone - gradual falloff
        falloff = 1.0 - ((freq_ratio - width) / (width * 2))
        eq_factor = 1.0 + (db_to_linear(eq_gain_db) - 1.0) * falloff
    else:
        # Outside EQ band - no effect
        eq_factor = 1.0
    
    return base_gain * eq_factor


def apply_shelf_eq(base_gain: float, shelf_gain_db: float, frequency: float, shelf_freq: float, is_high_shelf: bool = False) -> float:
    """Apply low or high shelf EQ."""
    if shelf_gain_db == 0.0:
        return base_gain
    
    # Determine if frequency is affected by shelf
    if is_high_shelf:
        # High shelf affects frequencies above shelf_freq
        if frequency >= shelf_freq:
            return base_gain * db_to_linear(shelf_gain_db)
    else:
        # Low shelf affects frequencies below shelf_freq
        if frequency <= shelf_freq:
            return base_gain * db_to_linear(shelf_gain_db)
    
    return base_gain


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


class EngineAudio:
    """Enhanced engine audio mixer with separated intake and engine sound systems.
    
    - Intake Sound: RPM-based only, no throttle volume modulation
    - Engine Sound: RPM + throttle-based volume and load mixing
    - Optional turbo spool and blow-off valve sounds
    """

    def __init__(self, intake_json: str = None, 
                 jbeam_file: str = None,
                 engine_json: str = None,
                 # --- Master volumes ---
                 engine_master_volume: float = 0.2,
                 turbo_master_volume: float = 0.4,
                 # --- Turbo parameters ---
                 turbo_wav: str = None,
                 turbo_min_pitch: float = 0.5,
                 turbo_max_pitch: float = 4,
                 turbo_volume: float = 0.5,
                 turbo_spool_rate: float = 2.5,  # how fast spool rises per second toward target
                 turbo_decay_rate: float = 1.2,  # how fast spool falls per second when off throttle
                 turbo_target_rpm: float = 8000.0,  # rpm at which turbo pitch reaches max
                 enable_turbo: bool = True,
                 # --- NEW: Multi-track turbo parameters ---
                 use_multitrack_turbo: bool = True,  # Use multi-track system instead of single file
                 turbo_sounds_dir: str = "turbo_14s_sounds",  # Directory with turbo_speed_X.X.wav files
                 turbo_min_speed: float = 1.0,  # Minimum speed multiplier for multi-track
                 turbo_max_speed: float = 5.0,  # Maximum speed multiplier for multi-track
                 # --- Blow-off valve (BOV) parameters ---
                 bov_wav: str = None,
                 bov_volume: float = 0.7,
                 bov_min_spool: float = 0.25,   # minimum internal spool to allow BOV
                 bov_min_throttle_drop: float = 0.35,  # required drop between last throttle and current
                 bov_cooldown: float = 0.35,     # seconds minimal gap between BOV plays
                 bov_spool_activation: float = 0.6,  # NEW: minimum spool (0-1) for BOV to even consider
                 bov_volume_curve: float = 0.85,  # NEW: exponent shaping for volume scaling vs spool
                 enable_bov: bool = True,
                 # --- Gear shift parameters ---
                 enable_gear_shifts: bool = True,
                 gear_shift_volume: float = 0.8,
                 aggressive_shift_threshold: float = 0.4,  # drift ratio threshold for aggressive shifts
                 # --- Engine cut during shift parameters ---
                 enable_engine_cut_on_shift: bool = True,  # Enable engine sound cut during gear shifts
                 engine_cut_factor: float = 0.1,  # Amount of engine sound to keep during shift (0.0-1.0)
                 ):
        """
        Initialize the enhanced engine audio system.
        
        Parameters:
        -----------
        intake_json : str
            Path to intake sound blend file (4_alt_int.sfxBlend2D.json)
        jbeam_file : str  
            Path to JBEAM file containing soundConfig (intake) and soundConfigExhaust (engine)
        engine_json : str
            Path to engine sound blend file (4_alt_exh.sfxBlend2D.json)
        """
        
        # Set default paths if not provided
        if intake_json is None:
            intake_json = asset_path("cars", "ae86", "sound", "blends", "4_alt_int.sfxBlend2D.json")
        if jbeam_file is None:
            jbeam_file = asset_path("cars", "ae86", "sound", "pessima_engine.jbeam")
        if engine_json is None:
            engine_json = asset_path("cars", "ae86", "sound", "blends", "4_alt_exh.sfxBlend2D.json")
        if turbo_wav is None:
            turbo_wav = asset_path("cars", "ae86", "sound", "turbo_03.wav")
        if bov_wav is None:
            bov_wav = asset_path("cars", "ae86", "sound", "turbo_bov.wav")
        
        # Load sound samples for intake and engine
        intake_data = json.load(open(intake_json))
        intake_audio_path = intake_data["samples"]
        
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
        
        # Load engine samples (exhaust) - if same as intake, will share the same audio data
        if engine_json and engine_json != intake_json:
            try:
                engine_data = json.load(open(engine_json))
                engine_audio_path = engine_data["samples"]
            except:
                print(f"Warning: Could not load engine samples from {engine_json}, using intake samples")
                engine_audio_path = intake_audio_path
        else:
            engine_audio_path = intake_audio_path
        
        # Calculate total sounds needed for mixer channels
        total_intake_sounds = len(intake_audio_path[0]) + len(intake_audio_path[1])
        total_engine_sounds = len(engine_audio_path[0]) + len(engine_audio_path[1])
        total_sounds = total_intake_sounds + total_engine_sounds
        
        current_channels = pygame.mixer.get_num_channels()
        if current_channels < total_sounds + 8:  # +8 for safety margin
            pygame.mixer.set_num_channels(total_sounds + 8)
            print(f"Increased mixer channels from {current_channels} to {total_sounds + 8}")
        
        # Detect car folder from JSON file paths for path resolution
        car_folder = asset_path("cars", "ae86", "sound")
        
        # Initialize intake sound layers
        self.intake_off = []
        for audio_off in intake_audio_path[0]:
            resolved_path = resolve_audio_path(audio_off[0], car_folder)
            sound_off = pygame.mixer.Sound(resolved_path)
            self.intake_off.append([sound_off, audio_off[1]])
            sound_off.play(loops=-1)
            sound_off.set_volume(0)
        
        self.intake_on = []
        for audio_on in intake_audio_path[1]:
            resolved_path = resolve_audio_path(audio_on[0], car_folder)
            sound_on = pygame.mixer.Sound(resolved_path)
            self.intake_on.append([sound_on, audio_on[1]])
            sound_on.play(loops=-1)
            sound_on.set_volume(0)
        
        # Initialize engine sound layers (formerly exhaust)
        self.engine_off = []
        for audio_off in engine_audio_path[0]:
            resolved_path = resolve_audio_path(audio_off[0], car_folder)
            sound_off = pygame.mixer.Sound(resolved_path)
            self.engine_off.append([sound_off, audio_off[1]])
            sound_off.play(loops=-1)
            sound_off.set_volume(0)
        
        self.engine_on = []
        for audio_on in engine_audio_path[1]:
            resolved_path = resolve_audio_path(audio_on[0], car_folder)
            sound_on = pygame.mixer.Sound(resolved_path)
            self.engine_on.append([sound_on, audio_on[1]])
            sound_on.play(loops=-1)
            sound_on.set_volume(0)
        
        print(f"Loaded intake: {len(self.intake_off)} off-throttle, {len(self.intake_on)} on-throttle sounds")
        print(f"Loaded engine: {len(self.engine_off)} off-throttle, {len(self.engine_on)} on-throttle sounds")
        print(f"Intake config: mainGain={self.intake_config.main_gain}dB, loadMix={self.intake_config.min_load_mix}-{self.intake_config.max_load_mix}")
        print(f"Engine config: mainGain={self.exhaust_config.main_gain}dB, loadMix={self.exhaust_config.min_load_mix}-{self.exhaust_config.max_load_mix}")
        
        # --- Limiter / headroom settings ---
        self.master_headroom = 0.85  # target max combined volume (mix of many loops)
        self.master_scale = 1.0      # dynamic scale updated each frame
        self.limiter_attack = 10.0   # how fast to reduce (gain units per second toward needed scale)
        self.limiter_release = 1.5   # how fast to recover toward 1.0 when below threshold
        self.enable_debug_limiter = False
        self.enable_debug_eq = False  # Debug EQ processing
        # Master volumes (independent global multipliers)
        self.engine_master_volume = max(0.0, min(2.0, float(engine_master_volume)))
        self.turbo_master_volume = max(0.0, min(2.0, float(turbo_master_volume)))

        # --- Turbo setup ---
        # Store turbo instance (no strict type annotation here to avoid runtime issues in some environments)
        self.turbo = None  # type: ignore
        self.turbo_enabled = False
        self.use_multitrack_turbo = use_multitrack_turbo
        self._turbo_spool = 0.0  # 0..1 internal spool ratio
        
        if enable_turbo:
            if use_multitrack_turbo and MultiTrackTurboSound is not None:
                # Try multi-track turbo system first
                try:
                    self.turbo = MultiTrackTurboSound(
                        turbo_sounds_dir,
                        min_speed=turbo_min_speed,
                        max_speed=turbo_max_speed
                    )
                    self.turbo_enabled = True
                    print(f"Multi-track turbo system initialized from {turbo_sounds_dir}")
                    print(f"  Speed range: {turbo_min_speed}x to {turbo_max_speed}x")
                    if hasattr(self.turbo, 'get_info'):
                        info = self.turbo.get_info()
                        print(f"  Loaded {info['tracks_loaded']} speed tracks")
                except Exception as e:  # pragma: no cover
                    print(f"Warning: Multi-track turbo failed, falling back to single-file system: {e}")
                    self.use_multitrack_turbo = False
            
            # Fallback to single-file system if multi-track failed or not requested
            if not self.turbo_enabled and turbo_wav and TurboSound is not None:
                try:
                    self.turbo = TurboSound(turbo_wav, min_pitch=turbo_min_pitch, max_pitch=turbo_max_pitch)
                    self.turbo_enabled = True
                    self.use_multitrack_turbo = False
                    print(f"Single-file turbo sound initialized from {turbo_wav}")
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
            "min_speed": turbo_min_speed,
            "max_speed": turbo_max_speed,
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

        # --- Gear shift sound setup ---
        self._gear_shift = None
        self._gear_shift_enabled = enable_gear_shifts and GearShiftSound is not None
        if self._gear_shift_enabled:
            try:
                self._gear_shift = GearShiftSound(
                    shift_up_volume=gear_shift_volume,
                    shift_down_volume=gear_shift_volume * 1.2,  # Downshifts slightly louder
                    gear_grind_volume=gear_shift_volume * 0.8
                )
                print("Gear shift sound system initialized")
            except Exception as e:
                print(f"Warning: Gear shift sound disabled ({e})")
                self._gear_shift_enabled = False
        
        self._aggressive_shift_threshold = max(0.0, min(1.0, aggressive_shift_threshold))
        
        # Engine cut during shift settings
        self.enable_engine_cut_on_shift = enable_engine_cut_on_shift
        self.engine_cut_factor = max(0.0, min(1.0, engine_cut_factor))

    def enable_turbo(self, enabled: bool = True):
        if enabled and self.turbo and not self.turbo_enabled:
            self.turbo_enabled = True
            print("Turbo sound enabled")
        elif not enabled and self.turbo_enabled:
            if self.turbo:
                self.turbo.stop()
            self.turbo_enabled = False
            print("Turbo sound disabled")

    def update(self, rpm: float, throttle: float, dt: float, 
               current_gear: int = 0, drift_ratio: float = 0.0) -> None:
        """Update engine audio with separated intake and engine sound systems."""
        # Clamp inputs
        throttle = max(0.0, min(1.0, throttle))
        rpm = max(0, rpm)
        dt = max(1e-5, dt)
        drift_ratio = max(0.0, min(1.0, drift_ratio))

        # --- Enhanced drift characteristics ---
        # Make engine more aggressive when drifting
        drift_boost_factor = 1.0 + (drift_ratio ** 1.5) * 0.4  # Up to 40% boost when fully drifting
        
        # Modify throttle response when drifting for more aggressive sound
        effective_throttle = throttle
        if drift_ratio > 0.3:
            # Make throttle response more snappy and aggressive during drift
            effective_throttle = min(1.0, throttle * drift_boost_factor)
            # Add some "pop" when lifting throttle during drift
            if throttle < 0.2 and drift_ratio > 0.5:
                effective_throttle = max(effective_throttle, 0.3 * drift_ratio)

        # --- 1. INTAKE SOUND: RPM-based only (no throttle volume modulation) ---
        # Intake sound is constant at given RPM, uses intakeMuffling for base volume
        intake_base_volume = self.intake_config.main_gain_linear * self.intake_config.intake_muffling
        if drift_ratio > 0.3:
            # Slight boost to intake during drift
            intake_base_volume *= (1.0 + drift_ratio * 0.15)
        
        # Calculate fundamental frequency for EQ processing
        fundamental_freq = calculate_fundamental_frequency(rpm, self.intake_config.fundamental_freq_cylinder_count)
        
        # Apply EQ processing to intake base volume
        intake_base_volume = self._apply_sound_config_eq(intake_base_volume, fundamental_freq, self.intake_config)
        
        # For intake, we mix between on/off based on load, but both contribute to overall volume
        intake_load_mix = calculate_load_mix(effective_throttle, 
                                           self.intake_config.max_load_mix, 
                                           self.intake_config.min_load_mix)
        
        intake_on_gain = intake_load_mix * self.intake_config.on_load_gain_linear * intake_base_volume
        intake_off_gain = (1.0 - intake_load_mix) * self.intake_config.off_load_gain_linear * intake_base_volume

        # --- 2. ENGINE SOUND: RPM + throttle-based volume and load mixing ---
        # Engine sound volume varies with throttle (higher throttle = louder engine)
        throttle_volume_factor = 0.3 + (effective_throttle * 0.7)  # 30% base + 70% throttle-dependent
        engine_base_volume = self.exhaust_config.main_gain_linear * throttle_volume_factor
        
        if drift_ratio > 0.3:
            # Boost engine more than intake during drift for more aggressive sound
            engine_base_volume *= drift_boost_factor

        # Apply EQ processing to engine base volume
        engine_base_volume = self._apply_sound_config_eq(engine_base_volume, fundamental_freq, self.exhaust_config)

        engine_load_mix = calculate_load_mix(effective_throttle, 
                                            self.exhaust_config.max_load_mix, 
                                            self.exhaust_config.min_load_mix)

        engine_on_gain = engine_load_mix * self.exhaust_config.on_load_gain_linear * engine_base_volume
        engine_off_gain = (1.0 - engine_load_mix) * self.exhaust_config.off_load_gain_linear * engine_base_volume

        # --- NEW: Engine sound cut during gear shifts ---
        # Cut engine sound (but NOT intake sound) during gear shifts for realism
        is_shifting = False
        if self._gear_shift and self._gear_shift_enabled and self.enable_engine_cut_on_shift:
            is_shifting = self._gear_shift.is_currently_shifting()
        
        if is_shifting:
            # Apply engine cut during shift - reduce engine sound based on cut factor
            engine_on_gain *= self.engine_cut_factor
            engine_off_gain *= self.engine_cut_factor
            # Note: intake sounds are NOT affected - they continue normally

        # --- 3. Layer pair normalization (on/off pairs) to keep crossfade sum <= 1.0 ---
        def normalize_pair(a: float, b: float, cap: float = 1.0):
            s = a + b
            if s > cap and s > 0.0:
                scale = cap / s
                return a * scale, b * scale
            return a, b

        intake_off_gain, intake_on_gain = normalize_pair(intake_off_gain, intake_on_gain, 1.0)
        engine_off_gain, engine_on_gain = normalize_pair(engine_off_gain, engine_on_gain, 1.0)

        # --- 4. Estimate combined mix energy heuristic (sum of active gains) ---
        # We approximate that at most one sample per pair is near peak at a time, but
        # across four lists we can exceed headroom; so sum the larger of each pair.
        est_mix = max(intake_off_gain, intake_on_gain) + max(engine_off_gain, engine_on_gain)

        # --- 5. Compute required global scale ---
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

        # --- 6. Apply global scale ---
        intake_off_gain *= self.master_scale * self.engine_master_volume
        intake_on_gain *= self.master_scale * self.engine_master_volume
        engine_off_gain *= self.master_scale * self.engine_master_volume
        engine_on_gain *= self.master_scale * self.engine_master_volume

        # --- 7. Update sound layers ---
        self._update_sound_layer(self.intake_off, rpm, intake_off_gain)
        self._update_sound_layer(self.intake_on, rpm, intake_on_gain)
        self._update_sound_layer(self.engine_off, rpm, engine_off_gain)
        self._update_sound_layer(self.engine_on, rpm, engine_on_gain)

        # --- 8. Enhanced turbo spool / playback with drift characteristics ---
        if self.turbo and self.turbo_enabled:
            # target spool is based on throttle and rpm fraction
            rpm_ratio = min(1.0, rpm / max(100.0, self._turbo_cfg["target_rpm"]))
            base_target = effective_throttle * rpm_ratio
            
            # Boost turbo spool during drift for more aggressive sound
            if drift_ratio > 0.3:
                drift_spool_boost = 1.0 + (drift_ratio ** 1.2) * 0.6  # Up to 60% boost when drifting
                base_target = min(1.0, base_target * drift_spool_boost)
            
            if base_target > self._turbo_spool:
                spool_gain = 0.2 + (drift_ratio * 0.3)  # Faster spool during drift
                self._turbo_spool = min(1.0, self._turbo_spool + self._turbo_cfg["spool_rate"] * dt * (base_target - self._turbo_spool + spool_gain))
            else:
                decay_rate = self._turbo_cfg["decay_rate"]
                # Slower decay during drift to maintain aggressive sound longer
                if drift_ratio > 0.4:
                    decay_rate *= (1.0 - drift_ratio * 0.4)
                self._turbo_spool = max(0.0, self._turbo_spool - decay_rate * dt * (self._turbo_spool - base_target + 0.05))
            
            # Calculate final parameters based on system type
            if self.use_multitrack_turbo:
                # Multi-track system: use speed factor instead of pitch
                speed_span = self._turbo_cfg["max_speed"] - self._turbo_cfg["min_speed"]
                speed_curve = 0.65 + (drift_ratio * 0.2)  # More aggressive speed curve when drifting
                speed_factor = self._turbo_cfg["min_speed"] + speed_span * (self._turbo_spool ** speed_curve)
                
                turbo_vol = self._turbo_cfg["volume"] * (0.3 + 0.7 * self._turbo_spool)
                # Boost turbo volume during drift
                if drift_ratio > 0.2:
                    turbo_vol *= (1.0 + drift_ratio * 0.5)
                turbo_vol *= self.turbo_master_volume
                
                # Use speed_factor for multi-track system
                self.turbo.play(speed_factor, volume=turbo_vol)
            else:
                # Legacy single-file system: use pitch
                pitch_span = self._turbo_cfg["max_pitch"] - self._turbo_cfg["min_pitch"]
                pitch_curve = 0.65 + (drift_ratio * 0.2)  # More aggressive pitch curve when drifting
                pitch = self._turbo_cfg["min_pitch"] + pitch_span * (self._turbo_spool ** pitch_curve)
                
                turbo_vol = self._turbo_cfg["volume"] * (0.3 + 0.7 * self._turbo_spool)
                # Boost turbo volume during drift
                if drift_ratio > 0.2:
                    turbo_vol *= (1.0 + drift_ratio * 0.5)
                turbo_vol *= self.turbo_master_volume
                
                # Use pitch for legacy system
                self.turbo.play(pitch, volume=turbo_vol)
        elif self.turbo and not self.turbo_enabled:
            self.turbo.stop()

        # --- 9. Enhanced BOV logic with drift sensitivity ---
        if self._bov_cfg["enabled"] and self._bov_sound:
            self._bov_time_since += dt
            drop = self._last_throttle - throttle
            
            # Make BOV more sensitive during drift
            min_drop = self._bov_cfg["min_drop"]
            if drift_ratio > 0.4:
                min_drop *= (1.0 - drift_ratio * 0.3)  # Easier to trigger BOV when drifting
            
            if (drop >= min_drop and
                self._turbo_spool >= self._bov_cfg["spool_activation"] and
                throttle < 0.2 and  # ensure mostly closed
                self._bov_time_since >= self._bov_cfg["cooldown"]):
                # play one-shot with drift-enhanced volume
                try:
                    self._bov_sound.stop()  # ensure retrigger crisp
                    bov_volume = self._compute_bov_volume()
                    if drift_ratio > 0.3:
                        bov_volume *= (1.0 + drift_ratio * 0.4)  # Louder BOV when drifting
                    self._bov_sound.set_volume(min(1.0, bov_volume))
                    self._bov_sound.play()
                except Exception:
                    pass
                self._bov_time_since = 0.0
        
        # --- 10. Gear shift sound update ---
        if self._gear_shift and self._gear_shift_enabled:
            self._gear_shift.update(current_gear, rpm, throttle, drift_ratio)
        
        self._last_throttle = throttle

    def stop_all(self):
        """Stop all looping sounds (engine layers + turbo + gear shifts)."""
        # Stop all sound layers
        for layer in (self.intake_off, self.intake_on, self.engine_off, self.engine_on):
            for snd, _ in layer:
                try:
                    snd.stop()
                except Exception:
                    pass
        if self.turbo:
            self.turbo.stop()
        
        # Stop gear shift sounds
        if self._gear_shift:
            self._gear_shift.stop_all()

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

    def _apply_sound_config_eq(self, base_gain: float, fundamental_freq: float, config: JBeamSoundConfig) -> float:
        """Apply EQ processing based on JBEAM soundConfig parameters."""
        processed_gain = base_gain
        original_gain = base_gain
        
        # Apply low shelf EQ
        if config.low_shelf_gain != 0.0:
            processed_gain = apply_shelf_eq(processed_gain, config.low_shelf_gain, 
                                          fundamental_freq, config.low_shelf_freq, is_high_shelf=False)
        
        # Apply high shelf EQ  
        if config.high_shelf_gain != 0.0:
            processed_gain = apply_shelf_eq(processed_gain, config.high_shelf_gain,
                                          fundamental_freq, config.high_shelf_freq, is_high_shelf=True)
        
        # Apply low parametric EQ
        if config.eq_low_gain != 0.0:
            processed_gain = apply_eq_gain(processed_gain, config.eq_low_gain,
                                         fundamental_freq, config.eq_low_freq, config.eq_low_width)
        
        # Apply high parametric EQ
        if config.eq_high_gain != 0.0:
            processed_gain = apply_eq_gain(processed_gain, config.eq_high_gain,
                                         fundamental_freq, config.eq_high_freq, config.eq_high_width)
        
        # Apply fundamental frequency EQ (targets the engine's fundamental frequency)
        if config.eq_fundamental_gain != 0.0:
            # Use a narrow width for fundamental EQ to be more precise
            fundamental_width = 0.05  # Narrower band for fundamental frequency
            processed_gain = apply_eq_gain(processed_gain, config.eq_fundamental_gain,
                                         fundamental_freq, fundamental_freq, fundamental_width)
        
        # Debug output
        if self.enable_debug_eq and abs(processed_gain - original_gain) > 0.01:
            eq_change_db = 20 * math.log10(processed_gain / original_gain) if original_gain > 0 else 0
            print(f"[EQ] {config.sample_name}: {fundamental_freq:.1f}Hz, gain change: {eq_change_db:+.1f}dB")
        
        return processed_gain

    def set_limiter_debug(self, enabled: bool):
        """Enable or disable limiter debug output."""
        self.enable_debug_limiter = enabled
        if enabled:
            print("Limiter debug enabled")
        else:
            print("Limiter debug disabled")

    def set_eq_debug(self, enabled: bool):
        """Enable or disable EQ debug output."""
        self.enable_debug_eq = enabled
        if enabled:
            print("EQ debug enabled")
        else:
            print("EQ debug disabled")

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
    
    # ------------------------------------------------------------------
    # Engine cut during shift controls
    # ------------------------------------------------------------------
    def set_engine_cut_on_shift(self, enabled: bool):
        """Enable or disable engine sound cut during gear shifts."""
        self.enable_engine_cut_on_shift = enabled
        print(f"Engine cut on shift: {'enabled' if enabled else 'disabled'}")
    
    def set_engine_cut_factor(self, factor: float):
        """Set the engine cut factor (0.0 = complete cut, 1.0 = no cut)."""
        self.engine_cut_factor = max(0.0, min(1.0, factor))
        print(f"Engine cut factor set to: {self.engine_cut_factor:.2f}")
    
    def get_engine_cut_settings(self):
        """Return current engine cut settings."""
        return {
            "enabled": self.enable_engine_cut_on_shift,
            "cut_factor": self.engine_cut_factor
        }


__all__ = ["EngineAudio", "JBeamSoundConfig", "db_to_linear", "calculate_load_mix", "parse_jbeam_file", 
           "calculate_fundamental_frequency", "apply_eq_gain", "apply_shelf_eq", "TurboSound", "MultiTrackTurboSound", "GearShiftSound"]
