import os, json, pygame
from pathlib import Path
import drift.config.const as const

class SaveManager:
    def __init__(self, game_name="drift_race"):
        appdata_path = os.getenv('APPDATA') # C:/Users/Name/AppData/Roaming
        if not appdata_path: # linux fallback
            appdata_path = os.path.expanduser('~')

        self.save_dir = Path(appdata_path) / game_name # C:/Users/Name/AppData/Roaming/drift_race
        self.save_dir.mkdir(parents=True, exist_ok=True) # create dir if not exists
        self.settings_file = self.save_dir / "settings.json" # C:/Users/Name/AppData/Roaming/drift_race/settings.json
        self.default_settings = { # default settings
            "audio": {"master": 1.0, "music": 1.0, "sfx": 1.0},
            "controls": {"up": "z", "down": "s", "left": "q", "right": "d", "handbrake": "space", "reset": "r", "steer_bias": 1.0},
            "stats": {"total_races": 0, "total_playtime": 0, "pbs": [None, None], "last_car": "AE86"},
            "cars_use": {"AE86": 0, "289": 0, "911": 0, "440": 0, "r34": 0, "s1e2": 0}
        }

    def load_settings(self):
        """load settings from appdata and create if missing."""
        if not self.settings_file.exists(): # if file doesnt exist, create with defaults
            self.save_settings(self.default_settings)
            return self.default_settings
        try:
            with open(self.settings_file, 'r') as f: return json.load(f)
        except json.JSONDecodeError: return self.default_settings # fallback to default settings if corrupted

    def apply_settings(self, audio_volumes, physics_controls):
        saved_settings = self.load_settings()

        # audio settings
        audio_volumes.set_value("master", saved_settings.get("audio", {}).get("master", 1.0))
        audio_volumes.set_value("music", saved_settings.get("audio", {}).get("music", 1.0))
        audio_volumes.set_value("sfx", saved_settings.get("audio", {}).get("sfx", 1.0))
        audio_volumes.update_sliders()

        # physics settings
        physics_controls.set_value("steer_bias", saved_settings.get("controls", {}).get("steer_bias", 1.0))

        # controls settings
        const.UP_KEY[1] = pygame.key.key_code(saved_settings.get("controls", {}).get("up", "z"))
        const.DOWN_KEY[1] = pygame.key.key_code(saved_settings.get("controls", {}).get("down", "s"))
        const.LEFT_KEY[1] = pygame.key.key_code(saved_settings.get("controls", {}).get("left", "q"))
        const.RIGHT_KEY[1] = pygame.key.key_code(saved_settings.get("controls", {}).get("right", "d"))
        const.BRAKE_KEY = pygame.key.key_code(saved_settings.get("controls", {}).get("handbrake", "space"))
        const.RESET_KEY = pygame.key.key_code(saved_settings.get("controls", {}).get("reset", "r"))

        # other
        const.CAR_ID = saved_settings.get("stats", {}).get("last_car", "AE86")
        const.GAME_PLAYED = saved_settings.get("stats", {}).get("total_races", 0)

    def build_data(self, audio_volumes, physics_controls):
        """build current settings data structure for saving."""
        return {
            "audio": {
                "master": audio_volumes.get_value("master"),
                "music": audio_volumes.get_value("music"),
                "sfx": audio_volumes.get_value("sfx")
            },
            "controls": {
                "up": pygame.key.name(const.UP_KEY[1]),
                "down": pygame.key.name(const.DOWN_KEY[1]),
                "left": pygame.key.name(const.LEFT_KEY[1]),
                "right": pygame.key.name(const.RIGHT_KEY[1]),
                "handbrake": pygame.key.name(const.BRAKE_KEY),
                "reset": pygame.key.name(const.RESET_KEY),
                "steer_bias": physics_controls.get_value("steer_bias")
            },
            "stats": {
                "total_races": const.GAME_PLAYED,
                "total_playtime": 0,
                "pbs": const.PBS,
                "last_car": const.CAR_ID
            },
            "cars_use": const.CARS_USE
        }

    def save_settings(self, audio_volumes, physics_controls):
        """writes current data to appdata."""
        data = self.build_data(audio_volumes, physics_controls)
        with open(self.settings_file, 'w') as f: json.dump(data, f, indent=4)
