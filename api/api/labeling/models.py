from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class MessageForLabeling(BaseModel):
    """Lightweight model for messages in the labeling workflow (GET response)."""

    id: str
    text: str
    label_classifier: Optional[Literal[0, 1]] = None


class LabeledData(BaseModel):
    """Base model for labeled data with all fields."""

    message_id: str
    text: str
    label_classifier: Optional[Literal[0, 1]] = None
    label_manual: Optional[Literal[0, 1]] = None
    created_at: datetime


class LabeledDataOut(LabeledData):
    """Model for labeled data returned from API (POST response)."""

    pass


class LabeledDataIn(BaseModel):
    """Model for submitting a manual label (POST request)."""

    message_id: str
    label_manual: Literal[0, 1]
