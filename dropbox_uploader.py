"""
Dropbox integration for uploading recordings
"""

import logging
import os
from typing import Any

import dropbox
from dropbox.exceptions import ApiError, AuthError

from config_manager import ConfigManager

logger = logging.getLogger(__name__)


class DropboxUploader:
    """Handles uploading files to Dropbox"""

    def __init__(self, config: ConfigManager) -> None:
        """
        Initialize Dropbox uploader

        Args:
            config: ConfigManager instance
        """
        self.config = config
        access_token = config.get("dropbox.access_token")

        if not access_token or access_token == "YOUR_DROPBOX_ACCESS_TOKEN_HERE":
            raise ValueError("Dropbox access token not configured")

        try:
            self.dbx = dropbox.Dropbox(access_token)
            # Test the connection
            self.dbx.users_get_current_account()
            logger.info("Successfully connected to Dropbox")
        except AuthError as e:
            raise ValueError(f"Invalid Dropbox access token: {e}")

        self.upload_path: str = config.get("dropbox.upload_path", "/AudioRecordings")

    def upload_file(self, local_path: str) -> bool:
        """
        Upload a file to Dropbox

        Args:
            local_path: Local file path to upload

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            filename = os.path.basename(local_path)
            dropbox_path = f"{self.upload_path}/{filename}"

            logger.info(f"Uploading {local_path} to Dropbox:{dropbox_path}")

            with open(local_path, "rb") as f:
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

    def list_files(self) -> list[Any]:
        """
        List files in the Dropbox upload folder

        Returns:
            list: List of file metadata
        """
        try:
            result = self.dbx.files_list_folder(self.upload_path)
            return result.entries
        except ApiError as e:
            logger.error(f"Error listing Dropbox files: {e}")
            return []