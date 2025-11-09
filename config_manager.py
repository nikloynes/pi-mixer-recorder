"""
Configuration management for the audio recorder
"""

import os
from typing import Any

import yaml


class ConfigManager:
    """Manages application configuration"""

    def __init__(self, config_path: str = "config.yaml") -> None:
        """
        Initialize configuration manager

        Args:
            config_path: Path to YAML configuration file
        """
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from YAML file"""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, "r") as f:
            config = yaml.safe_load(f)

        # Expand home directory in paths
        if "recording" in config and "local_storage_path" in config["recording"]:
            config["recording"]["local_storage_path"] = os.path.expanduser(
                config["recording"]["local_storage_path"]
            )

        return config

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation"""

        Args:
            key: Configuration key (e.g., 'audio.sample_rate')
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key.split(".")
        value: Any = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value using dot notation"""

        Args:
            key: Configuration key (e.g., 'audio.sample_rate')
            value: Value to set
        """
        keys = key.split(".")
        config: dict[str, Any] = self.config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def save(self) -> None:
        """Save configuration back to file"""
        with open(self.config_path, "w") as f:
            yaml.dump(self.config, f, default_flow_style=False)
