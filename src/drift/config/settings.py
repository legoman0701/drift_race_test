"""
Settings management for the drift game.
Handles UI sliders and persistent settings state.
"""
import drift.config.const as const

class SettingsManager:
    """Manages game settings including sliders and toggles."""
    
    def __init__(self, settings):
        # Settings state - these will sync with const values
        self.settings = settings
        self.sliders = {}
        
    def get_value(self, key):
        return self.settings.get(key, None)
    
    def set_value(self, key, value): # update value from key
        self.settings[key] = value

    def add_slider(self, key, slider):
        """Register a slider with the settings manager."""
        self.sliders[key] = slider
        
    def update_sliders(self):
        """Update all sliders to reflect current settings values."""
        for key, slider in self.sliders.items():
            if key in self.settings:
                slider.value = self.settings[key]
                
    def handle_slider_events(self, event):
        """Handle events for all managed sliders."""
        for key, slider in self.sliders.items():
            old_value = slider.value
            new_value = slider.handle_event(event)
            
            # If value changed, update settings
            if new_value != old_value:
                self.set_value(key, new_value)
                
    def draw_sliders(self, surface):
        """Draw all managed sliders."""
        for slider in self.sliders.values():
            slider.draw(surface)

controls = {
    'steer_bias': 1.0
}
physics_controls = SettingsManager(controls)

volumes = {
    'master_volume': 1.0,
    'music_volume': 1.0,
    'sfx_volume': 1.0
}
audio_volumes = SettingsManager(volumes)