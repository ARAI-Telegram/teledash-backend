from typing import Optional

from elasticsearch.dsl import Q
from fastapi import APIRouter, Depends, HTTPException, status

from api.accounts.auth import Account, get_current_active_verified_user
from api.database import get_database
from api.database.database import Database
from api.labeling.labeling import get_message_for_labeling, score_to_label
from api.labeling.models import LabeledDataIn, LabeledDataOut, MessageForLabeling
from common.utils import naive_utcnow


def get_labeling_router():
    router = APIRouter()
    current_active_verified_user = get_current_active_verified_user()

    @router.get(
        "/labeling",
        description="Get a message for manual labeling",
        tags=["labeling"],
        response_model=Optional[MessageForLabeling],
    )
    async def get_labeling_data(
        seed: Optional[int] = None,
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> Optional[MessageForLabeling]:
        """
        Get a random message that needs manual labeling (has classifier score, not yet labeled).
        Messages are sampled to maintain a 70:30 distribution of negative:positive classes.

        Args:
            seed: Optional seed for reproducible random sampling
        """
        return await get_message_for_labeling(seed=seed)

    @router.post(
        "/labeling",
        description="Submit manual label for a message",
        tags=["labeling"],
        response_model=LabeledDataOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def submit_label(
        data: LabeledDataIn,
        account: Account = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> LabeledDataOut:
        """Submit a manual label for a message."""
        # Check if already exists
        existing = await database.labeled_data.find_one(
            filter=Q("term", message_id=data.message_id)
        )

        if existing:
            # Update existing
            update_doc = {"label_manual": data.label_manual}
            updated = await database.labeled_data.update_one(
                query=Q("term", message_id=data.message_id), update=update_doc
            )
            return updated if updated else existing
        else:
            # Fetch message data from messages index
            message = await database.messages.find_one(
                filter=Q("term", _id=data.message_id)
            )
            if not message:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Message {data.message_id} not found",
                )

            # Get text and classifier label from the message
            text = message.text or message.caption or ""
            label_classifier = None
            if (
                hasattr(message, "classification_score_pos")
                and message.classification_score_pos is not None
            ):
                label_classifier = score_to_label(message.classification_score_pos)

            # Create new labeled data
            doc = {
                "message_id": data.message_id,
                "text": text,
                "label_classifier": label_classifier,
                "label_manual": data.label_manual,
                "created_at": naive_utcnow(),
            }
            await database.labeled_data.insert_one(document=doc, id=data.message_id)

            # Return the created document (no need to query it back)
            return LabeledDataOut(**doc)

    return router
