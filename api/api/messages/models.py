from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel

from api.database.database import StatsEntry


class MessageStatsFields(str, Enum):
    EXTRACTED_HASHTAGS = "extracted_hashtags"
    EXTRACTED_DOMAINS = "extracted_urls.domain"
    ATTACHMENT_TYPES = "attachment.type"
    TAGS = "tags"


class MessageStats(BaseModel):
    extracted_hashtags: Optional[List[StatsEntry]] = None
    extracted_domains: Optional[List[StatsEntry]] = None
    attachment_types: Optional[List[StatsEntry]] = None
    tags: Optional[List[StatsEntry]] = None


class MessageSearchType(str, Enum):
    EXACT = "exact"
    FLEXIBLE = "flexible"
    FUZZY = "fuzzy"
    SEMANTIC_TEXT = "semantic_text"
    SEMANTIC_IMAGE = "semantic_image"

    def is_semantic(self) -> bool:
        """Check if this search type is semantic (text or image)."""
        return self in (self.SEMANTIC_TEXT, self.SEMANTIC_IMAGE)


class MessageSearchFields(BaseModel):
    # Fields for standard/flexible search
    text: str
    caption: str
    transcription: str

    # Fields for exact search (minimal analyzer)
    text_exact: str
    caption_exact: str
    transcription_exact: str


MESSAGE_TEXT_SEARCH_FIELDS = MessageSearchFields(
    text="text",
    caption="caption",
    transcription="attachment.transcription",
    text_exact="text.minimal",
    caption_exact="caption.minimal",
    transcription_exact="attachment.transcription.minimal",
)


MESSAGE_SEARCH_TYPE_FIELD_MAP: Dict[MessageSearchType, List[str]] = {
    MessageSearchType.EXACT: [
        MESSAGE_TEXT_SEARCH_FIELDS.text_exact,
        MESSAGE_TEXT_SEARCH_FIELDS.caption_exact,
        MESSAGE_TEXT_SEARCH_FIELDS.transcription_exact,
    ],
    MessageSearchType.FLEXIBLE: [  # same as fuzzy
        MESSAGE_TEXT_SEARCH_FIELDS.text,
        MESSAGE_TEXT_SEARCH_FIELDS.caption,
        MESSAGE_TEXT_SEARCH_FIELDS.transcription,
    ],
    MessageSearchType.FUZZY: [
        MESSAGE_TEXT_SEARCH_FIELDS.text,
        MESSAGE_TEXT_SEARCH_FIELDS.caption,
        MESSAGE_TEXT_SEARCH_FIELDS.transcription,
    ],
    MessageSearchType.SEMANTIC_TEXT: [],  # fields are handled differently
    MessageSearchType.SEMANTIC_IMAGE: [],
}
