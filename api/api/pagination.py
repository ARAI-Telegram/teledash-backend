from typing import Any, List, Optional, Tuple, Union

from fastapi import Query
from pydantic import BaseModel

from api.accounts.models import AccountRead
from api.sort_config import (
    ChatSortOptions,
    ClientSortOptions,
    MessageSortOptions,
    SortOptions,
    UserSortOptions,
)
from common.database.models.chat import ChatOut
from common.database.models.client import ClientOut
from common.database.models.message import MessageOut
from common.database.models.user import UserOut

PaginationParams = Tuple[int, int, int]


class Pagination:
    def __init__(self, maximum_limit: int = 100) -> None:
        self.maximum_limit = maximum_limit

    def parse_params(
        self,
        skip: int = Query(0, ge=0),
        limit: int = Query(10, ge=0),
    ) -> PaginationParams:
        capped_limit = min(self.maximum_limit, limit)
        return (skip, capped_limit, self.maximum_limit)


class PaginatedResponseInfo(BaseModel):
    offset: int
    limit: int
    max_limit: int


class PaginatedResponse(BaseModel):
    data: Union[List[ChatOut], List[MessageOut], List[UserOut], List[ClientOut]]
    pagination: PaginatedResponseInfo
    sort: Optional[SortOptions]
    count_total: Optional[int]

    @classmethod
    def create(
        cls,
        data: List[Any],
        params: PaginationParams,
        sort: Optional[SortOptions] = None,
        count_total: Optional[int] = None,
    ) -> "PaginatedResponse":
        offset, limit, max_limit = params
        return cls(
            data=data,
            pagination=PaginatedResponseInfo(
                offset=offset, limit=limit, max_limit=max_limit
            ),
            sort=sort,
            count_total=count_total,
        )


class PaginatedChats(PaginatedResponse):
    data: List[ChatOut]
    sort: ChatSortOptions


class PaginatedMessages(PaginatedResponse):
    data: List[MessageOut]
    sort: MessageSortOptions


class PaginatedUsers(PaginatedResponse):
    data: List[UserOut]
    sort: UserSortOptions


class PaginatedClients(PaginatedResponse):
    data: List[ClientOut]
    sort: ClientSortOptions


class PaginatedAccounts(PaginatedResponse):
    data: List[AccountRead]
