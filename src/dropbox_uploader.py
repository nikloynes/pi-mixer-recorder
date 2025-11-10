"""Dropbox integration for uploading recordings."""

from pathlib import Path
from typing import Any

import dropbox
from dropbox.exceptions import ApiError
from loguru import logger

from src.config import get_settings

settings = get_settings()


class DropboxUploader:
    """Handles uploading files to Dropbox."""

    def __init__(self) -> None:
        """Initialise Dropbox uploader."""
        access_token = settings.dropbox.access_token.get_secret_value()

        if not access_token or access_token == "YOUR_DROPBOX_ACCESS_TOKEN_HERE":  # noqa: S105
            dropbox_token = "Dropbox access token not configured"  # noqa: S105
            raise ValueError(dropbox_token)

        self.dbx = dropbox.Dropbox(access_token)
        # est the connection
        self.dbx.users_get_current_account()
        logger.info("Successfully connected to Dropbox")

        self.upload_path: str = settings.dropbox.upload_path

    def upload_file(self, local_path: Path) -> bool:
        """
        Upload a file to Dropbox.

        Args:
            local_path: Local file path to upload

        Returns:
            bool: True if successful, False otherwise

        """
        try:
            filename = local_path.name
            dropbox_path = self.upload_path / Path(filename)

            logger.info(f"Uploading {local_path} to Dropbox:{dropbox_path}")

            with Path.open(local_path, "rb") as f:
                # Upload file (overwrite if exists)
                self.dbx.files_upload(
                    f.read(),
                    dropbox_path,
                    mode=dropbox.files.WriteMode("overwrite"),
                )

            logger.info(f"Successfully uploaded {filename} to Dropbox")
            return True

        except ApiError as e:
            logger.error(f"Dropbox API error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return False

    def list_files(self) -> Any:
        """
        List files in the Dropbox upload folder.

        Returns:
            list: List of file metadata

        """
        return self.dbx.files_list_folder(self.upload_path)
