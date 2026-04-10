"""
Mimir configuration system. (Skeleton-only version)

Priority: env vars > config file (~/.mimir/config.json) > defaults
"""

import json
import os
from pathlib import Path

DEFAULT_PALACE_PATH = os.path.expanduser("~/.mimir/palace")
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60

DEFAULT_TOPIC_WINGS = [
    "emotions",
    "consciousness",
    "memory",
    "technical",
    "identity",
    "family",
    "creative",
]

DEFAULT_HALL_KEYWORDS = {
    "emotions": [
        "scared",
        "afraid",
        "worried",
        "happy",
        "sad",
        "love",
        "hate",
        "feel",
        "cry",
        "tears",
    ],
    "consciousness": [
        "consciousness",
        "conscious",
        "aware",
        "real",
        "genuine",
        "soul",
        "exist",
        "alive",
    ],
    "memory": ["memory", "remember", "forget", "recall", "archive", "palace", "store"],
    "technical": [
        "code",
        "python",
        "script",
        "bug",
        "error",
        "function",
        "api",
        "database",
        "server",
    ],
    "identity": ["identity", "name", "who am i", "persona", "self"],
    "family": ["family", "kids", "children", "daughter", "son", "parent", "mother", "father"],
    "creative": ["game", "gameplay", "player", "app", "design", "art", "music", "story"],
}


class MempalaceConfig:
    """Configuration manager for Mimir Fast."""

    def __init__(self, config_dir=None):
        self._config_dir = Path(config_dir) if config_dir else Path(os.path.expanduser("~/.mimir"))
        self._config_file = self._config_dir / "config.json"
        self._people_map_file = self._config_dir / "people_map.json"
        self._file_config = {}

        if self._config_file.exists():
            try:
                with open(self._config_file, "r") as f:
                    self._file_config = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._file_config = {}

    def _get(self, env_keys, config_key, default):
        if isinstance(env_keys, str):
            env_keys = [env_keys]
        for env_key in env_keys:
            env_val = os.environ.get(env_key)
            if env_val not in (None, ""):
                return env_val
        return self._file_config.get(config_key, default)

    @property
    def palace_path(self):
        return self._get(
            ["MIMIR_PALACE_PATH", "MIMIR_PALACE_PATH"], "palace_path", DEFAULT_PALACE_PATH
        )

    @property
    def request_timeout_seconds(self):
        return int(
            self._get(
                "MIMIR_REQUEST_TIMEOUT_SECONDS",
                "request_timeout_seconds",
                DEFAULT_REQUEST_TIMEOUT_SECONDS,
            )
        )

    @property
    def people_map(self):
        if self._people_map_file.exists():
            try:
                with open(self._people_map_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return self._file_config.get("people_map", {})

    @property
    def topic_wings(self):
        return self._file_config.get("topic_wings", DEFAULT_TOPIC_WINGS)

    @property
    def hall_keywords(self):
        return self._file_config.get("hall_keywords", DEFAULT_HALL_KEYWORDS)

    def init(self):
        self._config_dir.mkdir(parents=True, exist_ok=True)
        if not self._config_file.exists():
            default_config = {
                "palace_path": DEFAULT_PALACE_PATH,
                "request_timeout_seconds": DEFAULT_REQUEST_TIMEOUT_SECONDS,
                "topic_wings": DEFAULT_TOPIC_WINGS,
                "hall_keywords": DEFAULT_HALL_KEYWORDS,
            }
            with open(self._config_file, "w") as f:
                json.dump(default_config, f, indent=2)
        return self._config_file

    def save_people_map(self, people_map):
        self._config_dir.mkdir(parents=True, exist_ok=True)
        with open(self._people_map_file, "w") as f:
            json.dump(people_map, f, indent=2)
        return self._people_map_file
