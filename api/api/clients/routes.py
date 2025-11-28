import logging
from typing import Optional, Tuple
from uuid import uuid4

from api.accounts.auth import get_current_active_verified_user
from api.accounts.models import AccountRead
from api.clients.add_chats import (
    assign_chat_username_to_client,
    get_username_for_chat_id,
)
from api.clients.authenticator import (
    TelegramAuthenticator,
    TwoFactorAuthenticationRequired,
    get_authenticator,
)
from api.clients.models import (
    AddChatRequest,
    ClientCreate,
    ClientUpdate,
    ClientVerifyPassword,
    ClientVerifyPhoneCode,
    SentCode,
)
from api.clients.validators import parse_client_filter, parse_client_sort
from api.database import get_database
from api.database.database import Database
from api.pagination import PaginatedClients, PaginatedResponse, Pagination
from api.sort_config import ClientSortOptions
from api.validators import FieldFilter, SortParams, parse_fields_params
from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from common.database.models.client import ClientIn, ClientOut
from common.settings import settings

logger = logging.getLogger(__name__)


def get_clients_router(app) -> APIRouter:
    """Create and configure the clients API router."""
    router = APIRouter()
    current_active_verified_user = get_current_active_verified_user()
    pagination = Pagination(maximum_limit=100)

    @router.get(  # Note: Complex search functionality would be better as POST /clients/search
        "/clients",
        response_description="List all clients",
        tags=["clients"],
        response_model=PaginatedClients,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def list_clients(
        filter: Optional[ESQuery] = Depends(parse_client_filter),
        sort: SortParams[ClientSortOptions] = Depends(parse_client_sort),
        fields: Optional[FieldFilter] = Depends(parse_fields_params),
        pagination: Tuple[int, int, int] = Depends(pagination.parse_params),
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> PaginatedResponse:
        """List Telegram client sessions with filtering, sorting, and pagination."""
        offset, limit, max_limit = pagination
        from_ = offset if offset else 0

        result = [
            doc
            async for doc in database.clients.find(
                filter=filter,
                fields=fields,
                from_=from_,
                size=limit,
                sort=sort,
            )
        ]

        return PaginatedClients.create(
            data=result,
            sort=sort[0],
            params=pagination,
        )

    @router.post(
        "/clients",
        response_description="Create a new client",
        tags=["clients"],
        response_model=ClientCreate,
        status_code=status.HTTP_201_CREATED,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def create_client(
        client: ClientIn,
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
        tg_auth: TelegramAuthenticator = Depends(get_authenticator),
    ) -> ClientCreate:
        """Create a new Telegram client session and initiate phone authentication."""
        new_client_id = uuid4()

        try:
            auth = await tg_auth.start_auth(
                title=client.title,
                client_id=str(new_client_id),
                api_id=client.api_id,
                api_hash=client.api_hash,
                phone_number=client.phone_number,
                test_mode=settings.telegram_test_mode,
            )
        except Exception as e:
            logger.error(f"Client session could not be initiated: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Client session could not be initiated",
            )

        client_dict = client.model_dump(exclude_none=True, by_alias=True)
        client_dict["is_active"] = False

        response = await database.clients.insert_one(
            document=client_dict, id=new_client_id
        )

        if not response:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Client could not be created",
            )
        client_dict["id"] = str(new_client_id)
        # Info: SentCode will be returned but won't be stored in DB.
        client_dict["auth"] = SentCode.from_pyrogram_sent_code(auth)

        return ClientCreate.model_validate(client_dict)

    @router.put(
        "/clients/{id}/verify-phone-code",
        response_description="Verify phone code for client authentication",
        tags=["clients"],
        response_model=ClientOut,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def verify_phone_code(
        id: str,
        phone_code_data: ClientVerifyPhoneCode,
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
        tg_auth: TelegramAuthenticator = Depends(get_authenticator),
    ) -> ClientOut:
        """Verify the phone code sent to the user's device to complete authentication."""
        search_query = Q("ids", values=[id])
        client_doc = await database.clients.find_one(filter=search_query)

        if not client_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Client with id {id} not found",
            )

        try:
            auth = await tg_auth.verify_phone_code(
                client_id=id,
                phone_number=client_doc.phone_number,
                phone_code_hash=phone_code_data.phone_code_hash,
                phone_code=phone_code_data.phone_code,
            )

            # Authentication completed successfully
            client_doc.session_hash = auth["session_hash"]
            client_doc.user_id = auth["user"].id

            update_query = client_doc.model_dump(
                exclude_unset=True, exclude_none=True, exclude={"id"}
            )

            updated_client_doc = await database.clients.update_one(
                query=search_query, update=update_query
            )

            if not updated_client_doc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Client {id} could not be updated",
                )

            return updated_client_doc

        except TwoFactorAuthenticationRequired as e:
            # 2FA required - return 403 status indicating additional authentication needed
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e),
            )

        except ValueError as e:
            logger.error(f"Phone code verification value error: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except Exception as e:
            logger.error(
                f"Phone code verification failed for client {id}: {e}", exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Phone code verification failed for client {id}",
            )

    @router.put(
        "/clients/{id}/verify-password",
        response_description="Verify 2FA/cloud password for client authentication",
        tags=["clients"],
        response_model=ClientOut,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def verify_password(
        id: str,
        password_data: ClientVerifyPassword,
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
        tg_auth: TelegramAuthenticator = Depends(get_authenticator),
    ) -> ClientOut:
        """Verify two-factor authentication password for clients with 2FA enabled."""
        search_query = Q("ids", values=[id])
        client_doc = await database.clients.find_one(filter=search_query)

        if not client_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Client with id {id} not found",
            )

        try:
            result = await tg_auth.verify_password(
                client_id=id,
                password=password_data.password,
            )

            # Update client with session info
            client_doc.session_hash = result["session_hash"]
            client_doc.user_id = result["user"].id

            update_query = client_doc.model_dump(
                exclude_unset=True, exclude_none=True, exclude={"id"}
            )

            updated_client_doc = await database.clients.update_one(
                query=search_query, update=update_query
            )

            if not updated_client_doc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Client {id} could not be updated",
                )

            return updated_client_doc

        except ValueError as e:
            logger.error(
                f"Password verification value error for client {id}: {e}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except Exception as e:
            logger.error(
                f"Password verification failed for client {id}: {e}", exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Password verification failed, client {id} could not be authenticated",
            )

    @router.get(
        "/clients/{id}",
        response_description="Get a single client",
        tags=["clients"],
        response_model=ClientOut,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def get_client(
        id: str,
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> ClientOut:
        """Retrieve a single Telegram client session by ID."""
        client_doc = await database.clients.find_one(filter=Q("ids", values=[id]))

        if not client_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Client with ID {id} not found",
            )

        return client_doc

    @router.put(
        "/clients/{id}",
        response_description="Update a client",
        tags=["clients"],
        response_model=ClientOut,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def update_client(
        id: str,
        client: ClientUpdate,
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> ClientOut:
        """Update client configuration such as active status and settings."""
        search_query = Q("ids", values=[id])
        update_query = client.model_dump(
            exclude_unset=True, exclude_none=True, by_alias=True
        )

        updated_client_doc = await database.clients.update_one(
            query=search_query, update=update_query
        )

        if not updated_client_doc:
            raise HTTPException(
                status_code=status.HTTP_304_NOT_MODIFIED,
                detail=f"Client with id {id} was not updated",
            )
        else:
            return updated_client_doc

    @router.delete(
        "/clients/{id}",
        response_description="Delete a client",
        tags=["clients"],
    )
    async def delete_client(
        id: str,
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> JSONResponse:
        """Delete a Telegram client session and terminate its connection."""
        response = await database.clients.delete_by_id(doc_id=id)

        if not response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Client with id {id} not found",
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_204_NO_CONTENT,
                content=f"Client with id {id} deleted.",
            )

    @router.post(
        "/clients/{client_id}/add-chat",
        response_description="Add a chat to the client's list of chats to join",
        tags=["clients"],
    )
    async def add_chat(
        client_id: str,
        request: AddChatRequest,
        account: AccountRead = Depends(current_active_verified_user),
        database: Database = Depends(get_database),
    ) -> JSONResponse:
        """Add a chat to the client's list of chats to join for scraping."""
        try:
            filter = Q("ids", values=[client_id])
            client_doc = await database.clients.find_one(filter=filter)
            if not client_doc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Client with id {client_id} not found",
                )

            username = await get_username_for_chat_id(request.chat_id, database)
            if username:
                result = await assign_chat_username_to_client(
                    client=client_doc, username=username, database=database
                )
                if result == "ALREADY_EXISTS":
                    return JSONResponse(
                        status_code=status.HTTP_304_NOT_MODIFIED,
                        content={
                            "status": "not_modified",
                            "message": "Chat is already in the list of channels to be joined.",
                            "data": {"username": username, "client_id": client_id},
                        },
                    )
                elif result == "SUCCESS":
                    return JSONResponse(
                        status_code=status.HTTP_201_CREATED,
                        content={
                            "status": "success",
                            "message": "Chat successfully added to list of chats to be joined.",
                            "data": {"username": username, "client_id": client_id},
                        },
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to update the client's list of chats to be joined.",
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=(
                        f"Adding chat with id {request.chat_id} failed. This probably means that the "
                        "chat is neither a recommended chat nor a chat that any message was "
                        "forwarded from. Only chats that are familiar to the scraper in one of "
                        "those ways can be joined."
                    ),
                )

        except HTTPException as http_exc:
            raise http_exc

        except Exception as e:
            logger.error(
                f"Unexpected error adding chat to client {client_id}: {e}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to add chat to client: {str(e)}",
            )

    return router
