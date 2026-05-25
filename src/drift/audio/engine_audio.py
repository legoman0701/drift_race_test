from __future__ import annotations

import json, math, pygame
from pathlib import Path
from dataclasses import dataclass
from drift.tools.paths import asset_path, normalize_asset_path
from drift.config.settings import audio_volumes


@dataclass(frozen=True)
class EngineTrack:
    group: str
    sound_path: Path
    bank_rpms: tuple[tuple[int, float], ...]


class V8EngineAudio:
    DEFAULT_GROUP_CONFIGS = {
        "eng": {
            "idle_volume": 0.05,
            "max_volume": 0.15,
            "throttle_curve": 0.55,
            "sigma_multiplier": 1,
            "rpm_response": 0.18,
            "audio_file": "v8chevyclassic_eng.sfxBlend2D.json",
        },
        "exh": {
            "idle_volume": 0.16,
            "max_volume": 0.33,
            "throttle_curve": 1.15,
            "sigma_multiplier": 1,
            "rpm_response": 0.26,
            "audio_file": "v8chevyclassic_exh.sfxBlend2D.json",
        },
    }
    TRACK_BLEND_RESPONSE = 0.22
    BANK_BLEND_RESPONSE = 0.18

    def __init__(self, engine_sound_id: str = "v8") -> None:
        self.engine_sound_id = str(engine_sound_id).strip() or "v8"
        self._group_configs = self._load_group_configs()
        self._channel_offset = 0
        self._channels: list[pygame.mixer.Channel] = []
        self._sounds: list[pygame.mixer.Sound] = []
        self._volumes: list[float] = []
        self._last_rpm = 0.0
        self._last_throttle = 0.0
        self._last_group_master: dict[str, float] = {group: 0.0 for group in self._group_configs}
        self._last_group_rpm: dict[str, float] = {group: 0.0 for group in self._group_configs}
        self._smoothed_group_rpm: dict[str, float] = {group: 0.0 for group in self._group_configs}
        self._last_weights: dict[str, list[float]] = {group: [] for group in self._group_configs}
        self._bank_mix: dict[str, list[float]] = {group: [] for group in self._group_configs}
        self._tracks = self._load_tracks()
        self._group_indices = self._build_group_indices()
        self._group_bank_indices = self._build_group_bank_indices()
        self._group_sigma = self._build_group_sigma()
        self._ensure_channel_pool(len(self._tracks))
        self._start_loops()

    def update(self, rpm: float, throttle: float) -> None:
        if not self._channels:
            return

        rpm = float(rpm)
        throttle = max(0.0, min(1.0, float(throttle)))
        target_volumes = [0.0] * len(self._tracks)
        self._last_rpm = rpm
        self._last_throttle = throttle

        for group_name, indices in self._group_indices.items():
            config = self._group_configs[group_name]
            group_master = self._compute_group_master(group_name, throttle)
            self._last_group_master[group_name] = group_master

            prev_group_rpm = self._smoothed_group_rpm[group_name]
            if prev_group_rpm <= 0.0:
                prev_group_rpm = rpm
            smoothed_group_rpm = prev_group_rpm + ((rpm - prev_group_rpm) * config["rpm_response"])
            self._smoothed_group_rpm[group_name] = smoothed_group_rpm
            self._last_group_rpm[group_name] = smoothed_group_rpm

            bank_mix = self._mix_group_banks(group_name, throttle)
            self._bank_mix[group_name] = bank_mix
            group_weights = self._mix_group_weights(group_name, smoothed_group_rpm, bank_mix)
            self._last_weights[group_name] = group_weights.copy()

            for local_index, track_index in enumerate(indices):
                target_volumes[track_index] = group_weights[local_index] * group_master

        for index, channel in enumerate(self._channels):
            target = target_volumes[index]
            current = self._volumes[index]
            smoothed = current + ((target - current) * self.TRACK_BLEND_RESPONSE)
            self._volumes[index] = smoothed
            coef = audio_volumes.get_value("master") * audio_volumes.get_value("sfx")
            channel.set_volume(smoothed * coef)

    def get_debug_snapshot(self) -> dict[str, object]:
        group_rows: dict[str, dict[str, object]] = {}
        for group_name, indices in self._group_indices.items():
            tracks = []
            weights = self._last_weights.get(group_name, [])
            bank_mix = self._bank_mix.get(group_name, [])
            for local_index, track_index in enumerate(indices):
                track = self._tracks[track_index]
                bank_names = [self._bank_name(bank_index) for bank_index, _ in track.bank_rpms]
                track_rpm = min((rpm for _, rpm in track.bank_rpms), default=0.0)
                tracks.append(
                    {
                        "label": track.sound_path.stem,
                        "banks": "/".join(bank_names),
                        "rpm": track_rpm,
                        "weight": weights[local_index] if local_index < len(weights) else 0.0,
                        "volume": self._volumes[track_index] if track_index < len(self._volumes) else 0.0,
                    }
                )

            group_rows[group_name] = {
                "master_volume": self._last_group_master.get(group_name, 0.0),
                "rpm": self._last_group_rpm.get(group_name, 0.0),
                "bank_mix": bank_mix,
                "tracks": tracks,
            }

        return {
            "rpm": self._last_rpm,
            "throttle": self._last_throttle,
            "groups": group_rows,
        }

    def stop_all(self) -> None:
        for channel in self._channels:
            try:
                channel.stop()
            except Exception:
                pass

    def _load_tracks(self) -> list[EngineTrack]:
        tracks_by_key: dict[tuple[str, Path], dict[int, float]] = {}

        for group_name in self._group_configs:
            blend_name = self._normalize_blend_filename(self._group_configs[group_name]["audio_file"])
            blend_path = asset_path("engines", self.engine_sound_id, blend_name)
            with open(blend_path, "r", encoding="utf-8") as handle:
                blend_data = json.load(handle)

            for bank_index, bank in enumerate(blend_data.get("samples", [])):
                for sample_path, rpm in bank:
                    resolved_path = self._resolve_sample_path(sample_path)
                    if not resolved_path.exists():
                        raise FileNotFoundError(f"Engine sample not found: {resolved_path}")
                    sample_key = (group_name, resolved_path)
                    bank_rpms = tracks_by_key.setdefault(sample_key, {})
                    bank_rpms[bank_index] = float(rpm)

        tracks: list[EngineTrack] = []
        for (group_name, resolved_path), bank_rpms in tracks_by_key.items():
            ordered_bank_rpms = tuple(sorted(bank_rpms.items(), key=lambda item: item[0]))
            tracks.append(EngineTrack(group=group_name, sound_path=resolved_path, bank_rpms=ordered_bank_rpms))

        tracks.sort(key=lambda track: (track.group, min(rpm for _, rpm in track.bank_rpms)))
        if not tracks:
            raise RuntimeError("No V8 engine audio tracks were found")
        return tracks

    def _load_group_configs(self) -> dict[str, dict[str, float]]:
        config_path = asset_path("engines", self.engine_sound_id, "engine.json")
        loaded_config: dict[str, object] = {}

        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                loaded_config = json.load(handle)
        except Exception:
            loaded_config = {}

        configured_groups = [
            group_name
            for group_name in self.DEFAULT_GROUP_CONFIGS
            if isinstance(loaded_config, dict) and isinstance(loaded_config.get(group_name), dict)
        ]
        group_names = configured_groups or list(self.DEFAULT_GROUP_CONFIGS.keys())

        merged_config: dict[str, dict[str, float]] = {}
        for group_name in group_names:
            defaults = self.DEFAULT_GROUP_CONFIGS[group_name]
            group_overrides = loaded_config.get(group_name, {}) if isinstance(loaded_config, dict) else {}
            if not isinstance(group_overrides, dict):
                group_overrides = {}

            merged_group = defaults.copy()
            for key, default_value in defaults.items():
                override_value = group_overrides.get(key, default_value)
                if key == "audio_file":
                    merged_group[key] = str(override_value or default_value)
                    continue

                try:
                    merged_group[key] = float(override_value)
                except (TypeError, ValueError):
                    merged_group[key] = float(default_value)

            merged_config[group_name] = merged_group

        return merged_config

    def _normalize_blend_filename(self, audio_file: str) -> str:
        normalized = str(audio_file).strip()
        if not normalized:
            raise RuntimeError("Engine audio config has an empty audio_file value")
        if not normalized.endswith(".json"):
            normalized = f"{normalized}.json"
        return normalized

    def _build_group_indices(self) -> dict[str, list[int]]:
        group_indices = {group_name: [] for group_name in self._group_configs}
        for index, track in enumerate(self._tracks):
            group_indices.setdefault(track.group, []).append(index)
        return group_indices

    def _build_group_bank_indices(self) -> dict[str, dict[int, list[int]]]:
        group_bank_indices: dict[str, dict[int, list[int]]] = {group_name: {} for group_name in self._group_configs}
        for index, track in enumerate(self._tracks):
            group_entry = group_bank_indices.setdefault(track.group, {})
            for bank_index, _ in track.bank_rpms:
                group_entry.setdefault(bank_index, []).append(index)
        return group_bank_indices

    def _build_group_sigma(self) -> dict[str, float]:
        sigma: dict[str, float] = {}
        for group_name, bank_indices in self._group_bank_indices.items():
            bank_sigmas = []
            for bank_index, indices in bank_indices.items():
                rpms = sorted(self._track_bank_rpm(self._tracks[index], bank_index) for index in indices)
                if len(rpms) < 2:
                    bank_sigmas.append(300.0)
                    continue
                gaps = [rpms[i + 1] - rpms[i] for i in range(len(rpms) - 1)]
                mean_gap = sum(gaps) / len(gaps)
                bank_sigmas.append(max(180.0, mean_gap * self._group_configs[group_name]["sigma_multiplier"]))
            sigma[group_name] = max(bank_sigmas) if bank_sigmas else 300.0
        return sigma

    def _resolve_sample_path(self, sample_path: str) -> Path:
        normalized = sample_path.replace("\\", "/")
        engine_prefix = "art/sound/engine/"
        if normalized.startswith(engine_prefix):
            relative_path = normalized[len(engine_prefix):].lstrip("/")
            engine_root = f"{self.engine_sound_id}/"
            if relative_path.startswith(engine_root):
                return normalize_asset_path("engines", relative_path)
            return normalize_asset_path("engines", self.engine_sound_id, relative_path)
        return normalize_asset_path(normalized)

    def _ensure_channel_pool(self, track_count: int) -> None:
        current_channels = pygame.mixer.get_num_channels()
        required_channels = track_count + 8
        if current_channels < required_channels:
            pygame.mixer.set_num_channels(required_channels)
        reserved_channels = pygame.mixer.set_reserved(track_count)
        if reserved_channels < track_count:
            raise RuntimeError("Unable to reserve enough mixer channels for engine audio")
        self._channel_offset = 0

    def _start_loops(self) -> None:
        for index, track in enumerate(self._tracks):
            sound = pygame.mixer.Sound(str(track.sound_path))
            channel = pygame.mixer.Channel(self._channel_offset + index)
            channel.play(sound, loops=-1)
            channel.set_volume(0.0)
            self._sounds.append(sound)
            self._channels.append(channel)
            self._volumes.append(0.0)

    def _compute_group_master(self, group_name: str, throttle: float) -> float:
        config = self._group_configs[group_name]
        throttle_mix = throttle**config["throttle_curve"]
        return config["idle_volume"] + ((config["max_volume"] - config["idle_volume"]) * throttle_mix)

    def _mix_group_banks(self, group_name: str, throttle: float) -> list[float]:
        bank_count = len(self._group_bank_indices.get(group_name, {}))
        if bank_count <= 1:
            return [1.0]

        target_load = max(0.0, min(1.0, throttle))
        previous_mix = self._bank_mix.get(group_name, [])
        if len(previous_mix) != bank_count:
            previous_mix = [1.0] + [0.0] * (bank_count - 1)

        load_mix = previous_mix[-1] + ((target_load - previous_mix[-1]) * self.BANK_BLEND_RESPONSE)
        load_mix = max(0.0, min(1.0, load_mix))

        if bank_count == 2:
            return [1.0 - load_mix, load_mix]

        mix = [0.0] * bank_count
        mix[0] = 1.0 - load_mix
        mix[-1] = load_mix
        return mix

    def _mix_group_weights(self, group_name: str, rpm: float, bank_mix: list[float]) -> list[float]:
        indices = self._group_indices[group_name]
        sigma = self._group_sigma[group_name]
        weights = [0.0] * len(indices)

        for local_index, track_index in enumerate(indices):
            track = self._tracks[track_index]
            track_weight = 0.0
            for bank_index, bank_rpm in track.bank_rpms:
                bank_factor = bank_mix[bank_index] if bank_index < len(bank_mix) else 0.0
                if bank_factor <= 0.0:
                    continue
                distance = rpm - bank_rpm
                gaussian = math.exp(-0.5 * ((distance / sigma) ** 2))
                track_weight += gaussian * bank_factor
            weights[local_index] = track_weight

        total = sum(weights)
        if total <= 1e-9:
            nearest_index = min(
                range(len(indices)),
                key=lambda idx: min(abs(bank_rpm - rpm) for _, bank_rpm in self._tracks[indices[idx]].bank_rpms),
            )
            weights = [0.0] * len(indices)
            weights[nearest_index] = 1.0
            return weights

        return [weight / total for weight in weights]

    def _track_bank_rpm(self, track: EngineTrack, bank_index: int) -> float:
        for current_bank_index, rpm in track.bank_rpms:
            if current_bank_index == bank_index:
                return rpm
        return track.bank_rpms[0][1]

    def _bank_name(self, bank_index: int) -> str:
        return "P" if bank_index == 1 else "N"