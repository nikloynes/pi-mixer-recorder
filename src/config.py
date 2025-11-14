"""Configuration management for the audio recorder."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_FILE_PATH = Path(__file__).parent.parent / "config.yaml"


class AudioSettings(BaseSettings):
    """Audio configuration settings."""

    sample_rate: int = Field(default=44100)
    channels: int = Field(default=2)
    chunk_size: int = Field(default=4096)
    device_index: int | None = Field(default=None)


class RecordingSettings(BaseSettings):
    """Recording configuration settings."""

    output_format: str = Field(default="wav")
    local_storage_path: Path = Field(default=Path("/home/pi/recordings"))
    filename_format: str = Field(default="recording_%Y%m%d_%H%M%S")


class DropboxSettings(BaseSettings):
    """Dropbox configuration settings."""

    enabled: bool = Field(default=True)
    access_token: SecretStr
    app_key: SecretStr
    app_secret: SecretStr
    refresh_token: SecretStr
    upload_path: str = Field(default="/pi_recordings")
    delete_local_after_upload: bool = Field(default=False)
    upload_in_background: bool = Field(default=True)

    @field_validator("upload_path", mode="after")
    @classmethod
    def ensure_posix_path(cls, v: str) -> str:
        """Ensure posix path (preceding `/`) for upload location."""
        if v[0] != "/":
            v = "/" + v
        return v


class GPIOSettings(BaseSettings):
    """GPIO configuration settings."""

    button_pin: int | None = Field(default=None)
    led_pin: int | None = Field(default=None)
    button_bounce_time: int = Field(default=300)


class WebSettings(BaseSettings):
    """Web UI configuration settings."""

    host: str = Field(default="localhost")
    port: int = Field(default=5000)
    debug: bool = Field(default=False)


class Settings(BaseSettings):
    """Combined settings model for the app."""

    audio: AudioSettings = Field(default_factory=AudioSettings)
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    dropbox: DropboxSettings = Field(default_factory=DropboxSettings)  # type: ignore[arg-type]
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

    def model_post_init(self, __context: object, /) -> None:
        """Post-initialization processing."""
        # Expand home directory in recording path
        self.recording.local_storage_path = Path(
            self.recording.local_storage_path
        ).expanduser()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()
