"""
Gear shift sound system for aggressive manual transmission feel.
Provides rough, aggressive gear shift sounds for drift racing.
"""

import pygame, time, threading
from typing import List


class GearShiftSound:
    """Aggressive gear shift sound system for manual transmission feel."""
    
    def __init__(self, 
                 gear_shift_samples: List[str] = None,
                 shift_up_volume: float = 0.4,
                 shift_down_volume: float = 0.2,
                 clutch_volume: float = 0.5,
                 gear_grind_volume: float = 0.4,
                 shift_timing_variance: float = 0.15,
                 # BOV parameters for powershifting
                 powershift_bov_volume: float = 0.05,
                 powershift_throttle_threshold: float = 0.6,
                 bov_sample_path: str = "assets/AE86/sound/turbo_bov.wav"):
        """
        Initialize gear shift sound system.
        
        Args:
            gear_shift_samples: List of paths to gear shift sound files
            shift_up_volume: Volume for upshift sounds (0.0-1.0)
            shift_down_volume: Volume for downshift sounds (0.0-1.0) 
            clutch_volume: Volume for clutch sounds (0.0-1.0)
            gear_grind_volume: Volume for gear grinding sounds (0.0-1.0)
            shift_timing_variance: Random timing variance for realistic feel (0.0-1.0)
        """
        self.shift_up_volume = max(0.0, min(1.0, shift_up_volume))
        self.shift_down_volume = max(0.0, min(1.0, shift_down_volume))
        self.clutch_volume = max(0.0, min(1.0, clutch_volume))
        self.gear_grind_volume = max(0.0, min(1.0, gear_grind_volume))
        self.shift_timing_variance = max(0.0, min(1.0, shift_timing_variance))
        
        # BOV parameters for powershifting
        self.powershift_bov_volume = max(0.0, min(1.0, powershift_bov_volume))
        self.powershift_throttle_threshold = max(0.0, min(1.0, powershift_throttle_threshold))
        
        # Load BOV sound for powershifting
        self.bov_sound = None
        try:
            self.bov_sound = pygame.mixer.Sound(bov_sample_path)
            print(f"Loaded powershift BOV sound: {bov_sample_path}")
        except Exception as e:
            print(f"Warning: Could not load BOV sound for powershifting: {e}")
        
        # Load default gear shift samples if none provided
        if gear_shift_samples is None:
            gear_shift_samples = [
                "assets/AE86/sound/gear_shift_1.wav",
                "assets/AE86/sound/gear_shift_2.wav", 
                "assets/AE86/sound/gear_shift_3.wav"
            ]
        
        self.shift_sounds = []
        for sample_path in gear_shift_samples:
            try:
                sound = pygame.mixer.Sound(sample_path)
                self.shift_sounds.append(sound)
                print(f"Loaded gear shift sound: {sample_path}")
            except Exception as e:
                print(f"Warning: Could not load gear shift sound {sample_path}: {e}")
        
        # Create synthetic gear shift sounds if no files loaded
        if not self.shift_sounds:
            print("No gear shift samples loaded, using synthetic sounds")
            self._create_synthetic_sounds()
        
        # State tracking - instant shift response
        self.last_gear = 0
        self.last_shift_time = 0.0
        self.shift_cooldown = 0.05  # Very short cooldown for instant shifting
        self.is_shifting = False
        self.shift_duration = 0.05  # Very short shift duration for instant feel
        
        # Thread safety
        self._shift_lock = threading.Lock()
        
    def _create_synthetic_sounds(self):
        """Create synthetic gear shift sounds if no samples available."""
        try:
            # Create white noise bursts for gear shifts
            sample_rate = 44100
            duration = 0.2
            samples = int(sample_rate * duration)
            
            import array
            import random
            
            # Shift sound 1: Quick burst
            shift_array = array.array('h', [int(random.randint(-32767, 32767) * 0.3) for _ in range(samples)])
            shift_sound = pygame.sndarray.make_sound(shift_array)
            self.shift_sounds.append(shift_sound)
            
            # Shift sound 2: Longer grind
            grind_array = array.array('h', [int(random.randint(-32767, 32767) * 0.2) for _ in range(int(samples * 1.5))])
            grind_sound = pygame.sndarray.make_sound(grind_array)
            self.shift_sounds.append(grind_sound)
            
            print("Created synthetic gear shift sounds")
            
        except Exception as e:
            print(f"Could not create synthetic gear shift sounds: {e}")
    
    def update(self, current_gear: int, rpm: float, throttle: float, drift_ratio: float = 0.0):
        """
        Update gear shift sound system.
        
        Args:
            current_gear: Current gear (0-based index)
            rpm: Current engine RPM
            throttle: Throttle position (0.0-1.0)
            drift_ratio: How much the car is drifting (0.0-1.0)
        """
        current_time = time.time()
        
        with self._shift_lock:
            # Check if we just shifted gears
            if current_gear != self.last_gear:
                time_since_last_shift = current_time - self.last_shift_time
                
                # Only trigger shift sound if enough time has passed
                if time_since_last_shift >= self.shift_cooldown:
                    # Check for powershift (throttle held during shift)
                    is_powershift = throttle >= self.powershift_throttle_threshold
                    
                    self._trigger_shift_sound(self.last_gear, current_gear, rpm, throttle, drift_ratio)
                    
                    # Trigger BOV sound for powershifts
                    if is_powershift and self.bov_sound:
                        self._trigger_powershift_bov(throttle, rpm, drift_ratio)
                    
                    self.last_shift_time = current_time
                    self.is_shifting = True
                
                self.last_gear = current_gear
            
            # Update shifting state
            if self.is_shifting and (current_time - self.last_shift_time) > self.shift_duration:
                self.is_shifting = False
    
    def _trigger_shift_sound(self, old_gear: int, new_gear: int, rpm: float, throttle: float, drift_ratio: float):
        """Trigger appropriate gear shift sound based on shift type and conditions."""
        if not self.shift_sounds:
            return
        
        # Determine shift type
        is_upshift = new_gear > old_gear
        is_downshift = new_gear < old_gear
        
        # Select sound based on conditions
        sound_index = 0
        volume = 0.5
        
        if is_upshift:
            # Upshift - more aggressive at high RPM or when drifting
            gear_jump = new_gear - old_gear
            if gear_jump > 1:
                # Penalize gear skipping with grinding sound
                sound_index = min(len(self.shift_sounds) - 1, 2)
                volume = self.gear_grind_volume * 1.5
                print(f"WARNING: Gear skip detected! {old_gear} -> {new_gear}")
            elif rpm > 6500 or drift_ratio > 0.4:
                sound_index = min(len(self.shift_sounds) - 1, 2)  # Most aggressive sound
                volume = self.shift_up_volume * (1.2 + drift_ratio * 0.4)
            elif rpm > 4500:
                sound_index = min(len(self.shift_sounds) - 1, 1)  # Medium sound
                volume = self.shift_up_volume * 0.9
            else:
                sound_index = 0  # Gentle sound
                volume = self.shift_up_volume * 0.7
                
        elif is_downshift:
            # Downshift - always more aggressive, especially when drifting
            gear_jump = old_gear - new_gear
            if gear_jump > 1:
                # Penalize gear skipping with grinding sound
                sound_index = min(len(self.shift_sounds) - 1, 2)
                volume = self.gear_grind_volume * 1.5
                print(f"WARNING: Gear skip detected! {old_gear} -> {new_gear}")
            elif drift_ratio > 0.3:
                sound_index = min(len(self.shift_sounds) - 1, 2)  # Most aggressive
                volume = self.shift_down_volume * (1.3 + drift_ratio * 0.6)
            else:
                sound_index = min(len(self.shift_sounds) - 1, 1)  # Medium aggressive
                volume = self.shift_down_volume * 1.1
        
        # Apply throttle influence (more aggressive when on throttle)
        if throttle > 0.7:
            volume *= 1.2
        elif throttle < 0.2:
            volume *= 0.7
        
        # Add some randomness for realism
        import random
        volume *= (0.9 + random.random() * 0.2)  # +/- 10% variance
        volume = max(0.0, min(1.0, volume))
        
        try:
            # Stop any currently playing shift sound
            for sound in self.shift_sounds:
                sound.stop()
            
            # Play the selected shift sound
            selected_sound = self.shift_sounds[sound_index]
            selected_sound.set_volume(volume*0.02)
            selected_sound.play()
            
            print(f"Gear shift: {old_gear} -> {new_gear}, RPM: {rpm:.0f}, Volume: {volume:.2f}")
            
        except Exception as e:
            print(f"Error playing gear shift sound: {e}")
    
    def _trigger_powershift_bov(self, throttle: float, rpm: float, drift_ratio: float):
        """Trigger BOV sound for powershifting (throttle held during shift)."""
        if not self.bov_sound:
            return
        
        try:
            # Calculate BOV volume based on throttle, RPM, and drift conditions
            base_volume = self.powershift_bov_volume
            
            # Scale volume based on throttle intensity
            throttle_factor = (throttle - self.powershift_throttle_threshold) / (1.0 - self.powershift_throttle_threshold)
            throttle_factor = max(0.0, min(1.0, throttle_factor))
            
            # Scale volume based on RPM (higher RPM = more pressure = louder BOV)
            rpm_factor = min(1.0, rpm / 7000.0)  # Normalize to redline
            
            # Scale volume based on drift (more aggressive when drifting)
            drift_factor = 1.0 + (drift_ratio * 0.5)
            
            # Calculate final volume
            final_volume = base_volume * throttle_factor * rpm_factor * drift_factor
            final_volume = max(0.0, min(1.0, final_volume))  # Ensure audible but not too loud
            
            # Play short BOV burst
            self.bov_sound.set_volume(final_volume)
            self.bov_sound.play()
            
            print(f"Powershift BOV: Throttle: {throttle:.2f}, RPM: {rpm:.0f}, Volume: {final_volume:.2f}")
            
        except Exception as e:
            print(f"Error playing powershift BOV sound: {e}")
    
    def force_shift_sound(self, shift_type: str = "up", volume: float = 0.8):
        """
        Manually trigger a gear shift sound.
        
        Args:
            shift_type: "up", "down", or "grind"
            volume: Volume level (0.0-1.0)
        """
        if not self.shift_sounds:
            return
        
        current_time = time.time()
        time_since_last = current_time - self.last_shift_time
        
        # Respect cooldown
        if time_since_last < self.shift_cooldown:
            return
        
        with self._shift_lock:
            if shift_type == "grind":
                sound_index = min(len(self.shift_sounds) - 1, 2)
                volume = min(volume, self.gear_grind_volume)
            elif shift_type == "down":
                sound_index = min(len(self.shift_sounds) - 1, 1)
                volume = min(volume, self.shift_down_volume)
            else:  # "up"
                sound_index = 0
                volume = min(volume, self.shift_up_volume)
            
            try:
                selected_sound = self.shift_sounds[sound_index]
                selected_sound.set_volume(volume)
                selected_sound.play()
                self.last_shift_time = current_time
            except Exception as e:
                print(f"Error playing manual shift sound: {e}")
    
    def set_volumes(self, shift_up: float = None, shift_down: float = None, 
                   clutch: float = None, gear_grind: float = None, 
                   powershift_bov: float = None):
        """Update volume levels for different shift types."""
        if shift_up is not None:
            self.shift_up_volume = max(0.0, min(1.0, shift_up))
        if shift_down is not None:
            self.shift_down_volume = max(0.0, min(1.0, shift_down))
        if clutch is not None:
            self.clutch_volume = max(0.0, min(1.0, clutch))
        if gear_grind is not None:
            self.gear_grind_volume = max(0.0, min(1.0, gear_grind))
        if powershift_bov is not None:
            self.powershift_bov_volume = max(0.0, min(1.0, powershift_bov))
    
    def force_powershift_bov(self, throttle: float = 0.8, rpm: float = 6000.0, drift_ratio: float = 0.0):
        """Manually trigger a powershift BOV sound."""
        if self.bov_sound:
            self._trigger_powershift_bov(throttle, rpm, drift_ratio)
    
    def stop_all(self):
        """Stop all currently playing gear shift sounds and BOV."""
        with self._shift_lock:
            for sound in self.shift_sounds:
                try:
                    sound.stop()
                except Exception:
                    pass
            
            # Also stop BOV sound
            if self.bov_sound:
                try:
                    self.bov_sound.stop()
                except Exception:
                    pass


__all__ = ["GearShiftSound"]