import time
from mimetypes import guess_type
from pathlib import Path
from typing import List, Union

from botocore.exceptions import BotoCoreError, ClientError
from celery.utils.log import get_task_logger
from elasticsearch.dsl import Q

from common.storage import Storage
from worker.database.database import Database
from worker.main import app
from worker.utils.helpers import bucket_name_from_attachment_type

logger = get_task_logger(__name__)
TMP_PATH = Path().cwd().joinpath("tmp")


class RetriableConnectionError(Exception):
    """Raised for connection/network errors that should trigger task retry."""

    pass


class NonRetriableError(Exception):
    """Raised for permanent errors (invalid data, missing files) that should be logged and skipped."""

    pass


def _upload_file_to_storage(
    file_path: str, bucket_name: str, object_name: str, storage: Storage
) -> None:
    """Upload a file to storage with content type detection.

    Args:
        file_path: Path to the file to upload.
        bucket_name: Storage bucket name.
        object_name: Object name in storage.
        storage: Storage instance.

    Raises:
        RetriableConnectionError: For connection/network errors that should trigger retry.
        NonRetriableError: For file not found or other permanent issues.
    """
    mime_type, _ = guess_type(file_path)

    try:
        storage.fput_object(bucket_name, object_name, file_path, content_type=mime_type)
    except FileNotFoundError:
        logger.warning(f"File {file_path} not found, skipping")
        raise NonRetriableError(f"File not found: {file_path}")
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Storage connection error uploading {file_path}: {e}")
        raise RetriableConnectionError(f"Storage connection error: {e}")


def _upload_and_cleanup_file(
    file_path: Path,
    bucket_name: str,
    object_name: str,
    storage: Storage,
    file_type: str,
) -> None:
    """Upload file to storage and remove local file.

    Args:
        file_path: Path to the file.
        bucket_name: Storage bucket name.
        object_name: Object name in storage.
        storage: Storage instance.
        file_type: Type of file (for logging).

    Raises:
        RetriableConnectionError: For connection errors that should trigger retry.
        NonRetriableError: For file issues that should skip this attachment.
    """
    if not file_path.is_file():
        logger.info(
            f"Skipping '{object_name}' (already uploaded or file does not exist)"
        )
        return

    _upload_file_to_storage(str(file_path), bucket_name, object_name, storage)
    logger.info(f"Uploaded {file_type.upper()} to storage '{object_name}'")

    # Clean up local file
    try:
        file_path.unlink()
    except FileNotFoundError:
        logger.warning(f"File {file_path} already deleted, continuing")


def _update_storage_refs_with_retry(
    database: Database,
    chat_id: Union[str, int],
    attachment_id: str,
    storage_refs: List[dict],
    max_retries: int = 3,
    retry_delay: int = 2,
) -> None:
    """Update storage references in database with retry logic.

    Args:
        database: Database instance.
        chat_id: Chat ID for the messages collection.
        attachment_id: ID of the attachment to update.
        storage_refs: List of storage reference dictionaries.
        max_retries: Maximum number of retry attempts.
        retry_delay: Delay in seconds between retries.

    Raises:
        RetriableConnectionError: For connection errors after retries exhausted.
        NonRetriableError: If document still not found after all retries.
    """
    save_data = {"storage_refs": storage_refs}

    for attempt in range(max_retries):
        try:
            database.get_messages_collection(chat_id).update_one(
                filter=Q("ids", values=[str(attachment_id)]),
                update={"attachment": save_data},
            )
            return
        except ValueError as e:
            # Document not found - might appear soon if message is being saved concurrently
            if attempt < max_retries - 1:
                logger.warning(
                    f"Attempt {attempt + 1}: Document not found for attachment {attachment_id}, retrying..."
                )
                time.sleep(retry_delay)
            else:
                # Still not found after retries - permanent error
                logger.error(
                    f"Document still not found for attachment {attachment_id} after {max_retries} attempts"
                )
                raise NonRetriableError(
                    f"Document not found for attachment {attachment_id}"
                ) from e
        except Exception as e:
            logger.error(
                f"Attempt {attempt + 1}: Couldn't update storage references for {attachment_id}. Error: {e}",
                exc_info=True,
            )

            if attempt < max_retries - 1:
                logger.info("Retrying..")
                time.sleep(retry_delay)
            else:
                # Connection error after retries - transient, should retry whole task
                raise RetriableConnectionError(
                    f"Failed to update storage reference for attachment {attachment_id} after {max_retries} attempts"
                ) from e


def _process_single_attachment(
    attachment: dict,
    chat_id: Union[str, int],
    storage: Storage,
    database: Database,
) -> None:
    """Process a single attachment: upload main file, thumbnail, and update database.

    Args:
        attachment: Attachment dictionary with type, file_name, id, and optional thumbnail.
        chat_id: Chat ID for database updates.
        storage: Storage instance.
        database: Database instance.

    Raises:
        RetriableConnectionError: For connection errors that should trigger task retry.
        NonRetriableError: For missing required fields or permanent failures.
    """
    # Validate required fields
    try:
        attachment_type = attachment["type"]
        object_name = attachment["file_name"]
        attachment_id = attachment["id"]
    except KeyError as e:
        raise NonRetriableError(f"Missing required field in attachment: {e}") from e

    bucket_name = bucket_name_from_attachment_type(attachment_type)
    file_path = TMP_PATH.joinpath("downloads", bucket_name, object_name)

    # Upload main attachment file
    _upload_and_cleanup_file(
        file_path, bucket_name, object_name, storage, attachment_type
    )

    # Build storage references
    storage_refs = [{"bucket": bucket_name, "object": object_name}]

    # Process thumbnail if present (thumbnails are optional)
    if "thumbnail" in attachment:
        thumb_object_name = attachment["thumbnail"]
        thumb_file_path = TMP_PATH.joinpath(
            "downloads", "thumbnails", thumb_object_name
        )

        try:
            _upload_and_cleanup_file(
                thumb_file_path, "thumbnails", thumb_object_name, storage, "thumbnail"
            )
            storage_refs.append({"bucket": "thumbnails", "object": thumb_object_name})
        except NonRetriableError as e:
            logger.warning(f"Skipping thumbnail for attachment {attachment_id}: {e}")
        except RetriableConnectionError:
            # Thumbnail connection error - re-raise to retry whole task
            raise

    # Update database with storage references
    _update_storage_refs_with_retry(database, chat_id, attachment_id, storage_refs)


@app.task(
    name="files_process.process_attachments",
    autoretry_for=(RetriableConnectionError,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=5,
)
def process_attachments(attachments: List[dict], chat_id: Union[str, int]) -> dict:
    """Process attachment files by uploading to storage and updating database.

    Uploads attachment files and thumbnails to object storage, then updates
    the corresponding message documents with storage references.

    Critical invariant: Files uploaded to storage MUST have database refs updated,
    or the task fails and retries. This prevents orphaned files in storage.

    Args:
        attachments: List of attachment dictionaries with type, file_name, id, and optional thumbnail.
        chat_id: Chat ID for database message collection.

    Returns:
        Dictionary with success_count, skipped_count, and total count.

    Raises:
        RetriableConnectionError: For connection issues, triggers Celery retry.
    """
    if not attachments:
        logger.info("No attachments to process")
        return {"success_count": 0, "skipped_count": 0, "total": 0}

    try:
        storage = Storage()
        database = Database()
    except Exception as e:
        logger.error(f"Failed to initialize storage or database: {e}")
        raise RetriableConnectionError("Failed to initialize connections") from e

    success = 0
    skipped = 0

    for attachment in attachments:
        try:
            _process_single_attachment(attachment, chat_id, storage, database)
            success += 1
        except NonRetriableError as e:
            # Permanent errors - skip this attachment
            skipped += 1
            logger.warning(
                f"Skipping attachment {attachment.get('id', 'unknown')}: {e}"
            )
        except RetriableConnectionError:
            # Connection errors - bubble up to trigger Celery retry
            logger.error(
                f"Connection error processing attachment {attachment.get('id', 'unknown')}, "
                f"task will retry. Progress: {success} succeeded, {skipped} skipped"
            )
            raise

        if (success + skipped) % 10 == 0:
            logger.info(
                f"Progress: {success + skipped}/{len(attachments)} "
                f"({success} succeeded, {skipped} skipped)"
            )

    logger.info(
        f"Completed processing {len(attachments)} attachments: "
        f"{success} succeeded, {skipped} skipped"
    )

    # Fail the task if nothing succeeded
    if success == 0 and len(attachments) > 0:
        raise RuntimeError(
            f"Failed to process any of {len(attachments)} attachments "
            f"({skipped} skipped due to permanent errors)"
        )

    return {
        "success": success,
        "skipped": skipped,
        "total": len(attachments),
    }
