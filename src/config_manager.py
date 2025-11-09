"""Configuration management for the audio recorder."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

# Configuration file path
CONFIG_FILE_PATH = Path(__file__).parent.parent / "config.yaml"


class AudioSettings(BaseSettings):
    """Audio configuration settings."""

    sample_rate: int = Field(default=48000)
    channels: int = Field(default=2)
    chunk_size: int = Field(default=1024)
    format: str = Field(default="paInt16")
    device_index: int | None = Field(default=None)


class RecordingSettings(BaseSettings):
    """Recording configuration settings."""

    output_format: str = Field(default="wav")
    local_storage_path: Path = Field(default=Path("/home/pi/recordings"))
    filename_format: str = Field(default="recording_%Y%m%d_%H%M%S")


class DropboxSettings(BaseSettings):
    """Dropbox configuration settings."""

    enabled: bool = Field(default=True)
    access_token: str = Field(default="YOUR_DROPBOX_ACCESS_TOKEN_HERE")
    upload_path: str = Field(default="/AudioRecordings")
    delete_local_after_upload: bool = Field(default=False)
    upload_in_background: bool = Field(default=True)


class GPIOSettings(BaseSettings):
    """GPIO configuration settings."""

    button_pin: int | None = Field(default=17)
    led_pin: int | None = Field(default=27)
    button_bounce_time: int = Field(default=300)


class WebSettings(BaseSettings):
    """Web UI configuration settings."""

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=5000)
    debug: bool = Field(default=False)


class Settings(BaseSettings):
    """Main settings model for the audio recorder."""

    audio: AudioSettings = Field(default_factory=AudioSettings)
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    dropbox: DropboxSettings = Field(default_factory=DropboxSettings)
    gpio: GPIOSettings = Field(default_factory=GPIOSettings)
    web: WebSettings = Field(default_factory=WebSettings)

    model_config = SettingsConfigDict(
        yaml_file=CONFIG_FILE_PATH,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Return the yaml settings with priority order."""
        return (
            YamlConfigSettingsSource(settings_cls),
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    def model_post_init(self, __context) -> None:
        """Post-initialization processing."""
        # Expand home directory in recording path
        self.recording.local_storage_path = Path(
            self.recording.local_storage_path
        ).expanduser()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()


# For backwards compatibility, create a simple interface
class ConfigManager:
    """Legacy configuration manager interface."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        """Initialize configuration manager."""
        global CONFIG_FILE_PATH
        CONFIG_FILE_PATH = Path(config_path)
        self._settings = get_settings()

    def get(self, key: str, default=None):
        """Get configuration value using dot notation."""
        keys = key.split(".")
        value = self._settings

        for k in keys:
            if hasattr(value, k):
                value = getattr(value, k)
            else:
                return default

        return value

    def set(self, key: str, value) -> None:
        """Set configuration value using dot notation."""
        keys = key.split(".")
        obj = self._settings

        for k in keys[:-1]:
            if hasattr(obj, k):
                obj = getattr(obj, k)
            else:
                raise ValueError(f"Invalid configuration key: {key}")

        setattr(obj, keys[-1], value)

    def save(self) -> None:
        """Save configuration back to file."""
        config_dict = self._settings.model_dump(mode="python")

        # Convert Path objects to strings for YAML serialization
        if "recording" in config_dict:
            config_dict["recording"]["local_storage_path"] = str(
                config_dict["recording"]["local_storage_path"]
            )

        with open(CONFIG_FILE_PATH, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False)
