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
            "stats": {"total_races": 0, "total_playtime": 0, "last_car": "AE86", "username": None},
            "cars": {
                "AE86": {"games_played": 0, "palette": None}, 
                "911": {"games_played": 0, "palette": None}, 
                "barracuda": {"games_played": 0, "palette": None}, 
                "mustang": {"games_played": 0, "palette": None}, 
                "r34": {"games_played": 0, "palette": None}, 
                "quattro": {"games_played": 0, "palette": None}  
            }, 
            "maps": {
                "1": {"games_played": 0, "best_time": None}, 
                "2": {"games_played": 0, "best_time": None}, 
            }
        }

    def load_settings(self):
        """load settings from appdata and create if missing."""
        if not self.settings_file.exists(): # if file doesnt exist, create with defaults
            self.save_settings(data=self.default_settings)
            return self.default_settings
        try:
            with open(self.settings_file, 'r') as f: return json.load(f)
        except json.JSONDecodeError: return self.default_settings # fallback to default settings if corrupted

    def apply_settings(self, audio_volumes, physics_controls):
        """load saved settings to edit current game settings"""
        saved_settings = self.load_settings()

        # audio settings
        audio_volumes.set_value("master", saved_settings.get("audio", {}).get("master", 1.0))
        audio_volumes.set_value("music", saved_settings.get("audio", {}).get("music", 1.0))
        audio_volumes.set_value("sfx", saved_settings.get("audio", {}).get("sfx", 1.0))
        # audio_volumes.update_sliders()

        # physics settings
        physics_controls.set_value("steer_bias", saved_settings.get("controls", {}).get("steer_bias", 1.0))

        # controls settings
        const.UP_KEY[1] = pygame.key.key_code(saved_settings.get("controls", {}).get("up", "z"))
        const.DOWN_KEY[1] = pygame.key.key_code(saved_settings.get("controls", {}).get("down", "s"))
        const.LEFT_KEY[1] = pygame.key.key_code(saved_settings.get("controls", {}).get("left", "q"))
        const.RIGHT_KEY[1] = pygame.key.key_code(saved_settings.get("controls", {}).get("right", "d"))
        const.BRAKE_KEY = pygame.key.key_code(saved_settings.get("controls", {}).get("handbrake", "space"))
        const.RESET_KEY = pygame.key.key_code(saved_settings.get("controls", {}).get("reset", "r"))

        # stats
        const.CAR_ID = saved_settings.get("stats", {}).get("last_car", "AE86")

        # palettes
        for car, data in saved_settings.get("cars", {}).items():
            if data["palette"] is not None:
                const.PALETTES[car] = tuple(tuple(c) for c in data["palette"])

    # Inside your SaveManager class
    def record_race_stats(self, race_duration, pb, pb_index):
        """update stats after a race"""
        data = self.load_settings()
        
        data["stats"]["total_races"] += 1
        data["stats"]["total_playtime"] += round(race_duration, 2)

        if const.CAR_ID not in data["cars"]: data["cars"][const.CAR_ID] = {"games_played": 0, "palette": None}
        data["cars"][const.CAR_ID]["games_played"] += 1

        if str(pb_index) not in data["maps"]: data["maps"][(str(pb_index))] = {"games_played": 0, "best_time": None}
        data["maps"][(str(pb_index))]["games_played"] += 1

        if pb is not None and (data["maps"][str(pb_index)]["best_time"] is None or pb < data["maps"][str(pb_index)]["best_time"]):
            data["maps"][str(pb_index)]["best_time"] = round(pb, 2)
        
        self.save_settings(data=data)

    def build_data(self, audio_volumes, physics_controls):
        """build current settings data structure for saving."""
        saved_settings = self.load_settings()
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
                "total_races": saved_settings.get("stats", {}).get("total_races", 0),
                "total_playtime": saved_settings.get("stats", {}).get("total_playtime", 0),
                "last_car": const.CAR_ID
            },
            "cars": {
                car: {
                    "games_played": saved_settings.get("cars", {}).get(car, {}).get("games_played", 0),
                    "palette": const.PALETTES.get(car, None)
                } for car in const.AVAILABLE_CARS
            },
            "maps": {
                str(index): {
                    "games_played": saved_settings.get("maps", {}).get(str(index), {}).get("games_played", 0),
                    "best_time": saved_settings.get("maps", {}).get(str(index), {}).get("best_time", None)
                } for index in range(1, const.TOTAL_MAPS +1) # -1 bc of tuto map
            }
        }

    def save_settings(self, data=None, audio_volumes=None, physics_controls=None):
        """writes current data to appdata."""
        if data is None:
            data = self.build_data(audio_volumes, physics_controls)
        with open(self.settings_file, 'w') as f: json.dump(data, f, indent=4)
