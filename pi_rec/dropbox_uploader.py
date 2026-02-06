"""Dropbox integration for uploading recordings."""

from pathlib import Path

import dropbox
from dropbox.exceptions import ApiError, AuthError
from dropbox.files import FileMetadata, ListFolderResult
from loguru import logger

from pi_rec.config import get_settings

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
                    oauth2_refresh_token=self.refresh_token,
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
        except ApiError as e:
            logger.error(f"Unexpected Dropbox API error during init: {e}")
            self._dbx = None

    @property
    def is_available(self) -> bool:
        """Check if the Dropbox client is connected and available."""
        return self._dbx is not None

    def upload_file(self, local_path: Path) -> bool:
        """Upload a file to Dropbox."""
        if not self.is_available or self._dbx is None:
            logger.warning("Dropbox upload skipped: client not available")
            return False

        filename = local_path.name
        dropbox_path = f"{self.upload_path.rstrip('/')}/{filename}"
        logger.info(f"Uploading {local_path} -> {dropbox_path}")
        try:
            with local_path.open("rb") as f:
                self._dbx.files_upload(
                    f.read(), dropbox_path, mode=dropbox.files.WriteMode("overwrite")
                )
        except AuthError as e:
            logger.error(f"Auth error during upload: {e} (maybe token expired)")
            return False
        except ApiError as e:
            logger.error(f"Dropbox API error during upload: {e}")
            return False
        except OSError as e:
            logger.error(f"File read error: {e}")
            return False
        else:
            logger.info(f"Uploaded {filename}")
            return True

    def list_files(self) -> list[FileMetadata]:
        """List files in the Dropbox folder."""
        if not self.is_available or self._dbx is None:
            logger.warning("Dropbox list skipped: client not available")
            return []

        try:
            result: ListFolderResult = self._dbx.files_list_folder(self.upload_path)
        except AuthError as e:
            logger.error(f"Auth error listing files: {e}")
            return []
        except ApiError as e:
            logger.error(f"Dropbox API error listing files: {e}")
            return []
        else:
            return result.entries  # type: ignore[no-any-return]
