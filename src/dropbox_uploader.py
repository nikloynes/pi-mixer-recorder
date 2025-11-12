"""Dropbox integration for uploading recordings."""

from pathlib import Path
from typing import Any

import dropbox
from dropbox.exceptions import ApiError, AuthError
from loguru import logger

from src.config import get_settings

settings = get_settings()


class DropboxUploader:
    """Handles uploading files to Dropbox with auto refresh support."""

    def __init__(self) -> None:
        """Initialise DropboxUploader."""
        self.app_key: str = settings.dropbox.app_key.get_secret_value()
        self.app_secret: str = settings.dropbox.app_secret.get_secret_value()
        self.access_token: str = settings.dropbox.access_token.get_secret_value()
        self.refresh_token: str = settings.dropbox.refresh_token.get_secret_value()
        self.upload_path: str = settings.dropbox.upload_path
        self._dbx: dropbox.Dropbox | None = None
        self._connect()

    def _connect(self) -> None:
        """Create Dropbox client (with refresh support if available)."""
        if not self.access_token and not self.refresh_token:
            logger.warning("Dropbox disabled: no access or refresh token configured")
            return

        try:
            if self.refresh_token and self.app_key and self.app_secret:
                # Preferred: long-lived via refresh token
                self._dbx = dropbox.Dropbox(
                    app_key=self.app_key,
                    app_secret=self.app_secret,
                    oauth2_refresh_token=self.refresh_token,  # get this via utils/
                )
            else:
                # Fallback: short-lived access token (will expire)
                self._dbx = dropbox.Dropbox(oauth2_access_token=self.access_token)

            # Test auth
            self._dbx.users_get_current_account()
            logger.info("Connected to Dropbox")
        except AuthError as e:
            logger.error(f"Dropbox auth failed: {e}. Configure refresh token.")
            self._dbx = None
        except Exception as e:
            logger.exception(f"Unexpected Dropbox init error: {e}")
            self._dbx = None

    @property
    def is_available(self) -> bool:
        return self._dbx is not None

    def upload_file(self, local_path: Path) -> bool:
        """Upload a file to Dropbox."""
        if not self.is_available:
            logger.warning("Dropbox upload skipped: client not available")
            return False
        try:
            filename = local_path.name
            dropbox_path = f"{self.upload_path.rstrip('/')}/{filename}"
            logger.info(f"Uploading {local_path} -> {dropbox_path}")
            with local_path.open("rb") as f:
                self._dbx.files_upload(
                    f.read(), dropbox_path, mode=dropbox.files.WriteMode("overwrite")
                )
            logger.info(f"Uploaded {filename}")
            return True
        except AuthError as e:
            logger.error(f"Auth error during upload: {e} (maybe token expired)")
            return False
        except ApiError as e:
            logger.error(f"Dropbox API error: {e}")
            return False
        except Exception as e:
            logger.error(f"Upload error: {e}")
            return False

    def list_files(self) -> Any:
        """List files in the Dropbox folder."""
        if not self.is_available:
            logger.warning("Dropbox list skipped: client not available")
            return []
        try:
            return self._dbx.files_list_folder(self.upload_path)
        except AuthError as e:
            logger.error(f"Auth error listing files: {e}")
            return []
        except Exception:
            logger.exception("Error listing Dropbox files")
            return []
