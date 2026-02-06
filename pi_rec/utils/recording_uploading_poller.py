"""
A background service that polls for finished recordings,
uploads them to Dropbox,
and then deletes them locally.
"""

import time
from pathlib import Path

from pi_rec.config import get_settings
from pi_rec.dropbox_uploader import DropboxUploader
from pi_rec.logger import logger

# How long a file must be unmodified before we consider it "finished" (in seconds)
FILE_STABILITY_THRESHOLD = 20
# How often to scan the directory for new files (in seconds)
POLL_INTERVAL = 15


def is_file_stable(file_path: Path) -> bool:
    """
    Check if a file has not been modified recently.

    Args:
        file_path: The path to the file.

    Returns:
        True if the file is considered stable, False otherwise.

    """
    try:
        file_mod_time = file_path.stat().st_mtime
        return (time.time() - file_mod_time) > FILE_STABILITY_THRESHOLD
    except FileNotFoundError:
        logger.warning(f"File not found during stability check: {file_path.name}")
        return False


def upload_recording(uploader: DropboxUploader, file_path: Path) -> bool:
    """
    Upload a single recording to Dropbox.

    Args:
        uploader: The DropboxUploader instance.
        file_path: The path to the local file to upload.

    Returns:
        True if the upload was successful, False otherwise.

    """
    logger.info(f"Attempting to upload {file_path.name}...")
    return uploader.upload_file(file_path)


def delete_local_recording(file_path: Path) -> None:
    """
    Delete a local recording file.

    Args:
        file_path: The path to the local file to delete.

    """
    try:
        file_path.unlink()
        logger.info(f"Deleted local file: {file_path.name}")
    except FileNotFoundError:
        logger.warning(f"File not found during deletion: {file_path.name}")
    except OSError as e:
        logger.error(f"Error deleting file {file_path.name}: {e}")


def run_stability_upload_delete_pipeline(
    uploader: DropboxUploader, file_path: Path, *, delete_after_upload: bool = True
) -> bool:
    """
    Orchestrate the checking, uploading, and deleting for a single file.

    Args:
        uploader: The DropboxUploader instance.
        file_path: The path to the file to process.
        delete_after_upload: Flag indicating whether to delete the file after upload.

    Returns:
        True if the file was successfully uploaded, False otherwise.

    """
    if not is_file_stable(file_path):
        logger.debug(f"File {file_path.name} is not stable yet.")
        return False

    logger.info(f"Found stable recording: {file_path.name}")
    upload_successful = upload_recording(uploader, file_path)

    if upload_successful and delete_after_upload:
        delete_local_recording(file_path)
    elif not upload_successful:
        logger.warning(f"Upload failed for {file_path.name}. Will retry later.")

    return upload_successful


def main() -> None:
    """Poll for files and upload them."""
    settings = get_settings()
    recordings_dir = settings.recording.local_storage_path

    if not recordings_dir.is_dir():
        logger.info(f"Recordings directory not found, creating: {recordings_dir}")
        recordings_dir.mkdir(parents=True, exist_ok=True)

    uploader = DropboxUploader()
    if not uploader.is_available:
        logger.error(
            "Dropbox is not configured or available. Uploader service exiting."
        )
        return

    # use set to prevent re-uploading if `delete_after_upload` is False.
    uploaded_files_session_cache: set[Path] = set()

    logger.info("Dropbox Uploader service started.")
    logger.info(f"Watching for new files in: {recordings_dir}")

    while True:
        try:
            local_files = list(recordings_dir.glob("*.wav"))
        except OSError as e:
            logger.error(f"Could not read directory {recordings_dir}: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        # Prune the cache: remove entries for files that no longer exist locally
        uploaded_files_session_cache = {
            f for f in uploaded_files_session_cache if f.exists()
        }

        for file_path in local_files:
            if not file_path.is_file() or file_path in uploaded_files_session_cache:
                continue

            upload_was_successful = run_stability_upload_delete_pipeline(
                uploader=uploader,
                file_path=file_path,
                delete_after_upload=settings.dropbox.delete_local_after_upload,
            )

            if upload_was_successful:
                uploaded_files_session_cache.add(file_path)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
