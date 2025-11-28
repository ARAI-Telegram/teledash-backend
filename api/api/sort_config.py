from enum import Enum
from typing import List, Sequence, TypeVar, Union

from pydantic import BaseModel

from common.database.models.message import MessageOut


class OrderEnum(str, Enum):
    ASC = "asc"
    DESC = "desc"


class ChatSortBy(str, Enum):
    TITLE = "title.keyword"
    MEMBERS_COUNT = "members_count"
    UPDATED_AT = "updated_at"
    SCORE = "score"


class MessageSortBy(str, Enum):
    DATE = "date"
    SCORE = "score"
    CONSPIRACY = "classification.score_pos"


class UserSortBy(str, Enum):
    SCORE = "score"
    USERNAME = "username.keyword"
    UPDATED_AT = "updated_at"


class ClientSortBy(str, Enum):
    TITLE = "title"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


SortByEnum = Union[ChatSortBy, MessageSortBy, UserSortBy, ClientSortBy]


class SortOptions(BaseModel):
    sort_by: SortByEnum
    order: OrderEnum


class MessageSortOptions(SortOptions):
    sort_by: MessageSortBy


class ChatSortOptions(SortOptions):
    sort_by: ChatSortBy


class UserSortOptions(SortOptions):
    sort_by: UserSortBy


class ClientSortOptions(SortOptions):
    sort_by: ClientSortBy


TypedSortOptions = TypeVar("TypedSortOptions", bound=SortOptions)
SortParams = Sequence[TypedSortOptions]

DEFAULT_SORT_OPTIONS = {
    ChatSortOptions: [ChatSortOptions(sort_by=ChatSortBy.TITLE, order=OrderEnum.ASC)],
    MessageSortOptions: [
        MessageSortOptions(sort_by=MessageSortBy.DATE, order=OrderEnum.DESC)
    ],
    UserSortOptions: [
        UserSortOptions(sort_by=UserSortBy.USERNAME, order=OrderEnum.ASC)
    ],
    ClientSortOptions: [
        ClientSortOptions(sort_by=ClientSortBy.TITLE, order=OrderEnum.ASC)
    ],
}


def sort_semantic_search_results(
    result_messages: List[MessageOut], sort: SortParams
) -> List[MessageOut]:
    """
    Sort semantic search results with special handling for score field.
    
    Maps the "score" field to "semantic_score" (which is set by the semantic API)
    and applies the requested sort order. Handles None values by treating them
    as -infinity to push them to the end when sorting descending.
    
    Args:
        result_messages: List of messages returned from semantic search API
        sort: Sort parameters with sort_by field and order (ASC/DESC)
    
    Returns:
        Sorted list of messages with None values at the end (for DESC) or start (for ASC)
    
    Note: Consider moving to validators module for better organization
    """
    # extract and adapt sorting params
    sort_field = sort[0].sort_by
    if sort_field == "score":
        sort_field = "semantic_score"
    sort_order = sort[0].order
    reverse_order = sort_order == OrderEnum.DESC

    return sorted(
        result_messages,
        key=lambda x: getattr(x, sort_field)
        if getattr(x, sort_field, None) is not None
        else float("-inf"),
        reverse=reverse_order,
    )
