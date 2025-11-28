from datetime import timedelta

from botocore.exceptions import BotoCoreError, ClientError
from celery.utils.log import get_task_logger
from elasticsearch.dsl import Q

from common.settings import settings
from common.storage import Storage
from common.utils import naive_utcnow
from worker.database.database import Database
from worker.main import app

logger = get_task_logger(__name__)


@app.task(name="files_purge.purge_message_attachments")
def purge_message_attachments() -> dict:
    if settings.keep_attachment_files_days == 0:
        raise ValueError(
            'Trying to purge attachment files as scheduled, but setting is set to "0 days" (indefinitely)'  # noqa: E501
        )

    database = Database()
    storage = Storage()
    delete_count = 0

    # Get all message indices (e.g., messages_* indices)
    message_indices = database.find_all_message_indices()

    if not message_indices:
        logger.info("No message indices found for purging attachments.")
        return {"delete_count": delete_count}

    # get message documents with attachments in storage
    date_threshold = naive_utcnow() - timedelta(
        days=settings.keep_attachment_files_days
    )

    filter = Q(
        "bool",
        filter=[
            Q("range", date={"lt": date_threshold}),
            Q("exists", field="attachment.storage_refs"),
        ],
    )

    for index in message_indices:
        logger.info(f"Processing index: {index}")
        # Extract chat_id from index name (messages_{chat_id})
        chat_id = index.replace("messages_", "")
        messages_collection = database.get_messages_collection(chat_id)

        messages_cursor = messages_collection.find(
            filter=filter, fields={"includes": ["attachment.storage_refs"]}
        )

        for message in messages_cursor:
            if not message.attachment or not message.attachment.storage_refs:
                continue

            for ref in message.attachment.storage_refs:
                try:
                    # remove object in storage
                    storage.remove_object(ref.bucket, ref.object)
                except (ClientError, BotoCoreError) as e:
                    logger.error(
                        f'Error removing file "{ref.bucket}/{ref.object}" from storage: {e}',
                        exc_info=True,
                    )
                    # Continue to next message - don't fail entire purge on one file error
                    break
            else:
                # remove storage refs in database for message attachment
                update = {
                    "script": {
                        "script": "ctx._source.attachment.remove('storage_refs')",
                        # ES requires scripting to delete a field
                        "lang": "painless",
                    }
                }
                messages_collection.update_one(
                    filter=Q("ids", values=[message.id]), update=update
                )
                delete_count += 1
                logger.info(f"Removed attachments for message {message.id}")

    database.close()

    return {"delete_count": delete_count}
