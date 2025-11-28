from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Response
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import select

from api.accounts.auth import (
    Account,
    auth_backend,
    get_account_db,
    get_current_active_verified_superuser,
    get_current_active_verified_user,
    get_fast_api_users,
    get_jwt_strategy,
)
from api.accounts.models import AccountCreate, AccountRead, AccountUpdate
from api.pagination import PaginatedAccounts, PaginatedResponse, Pagination
from api.validators import FieldFilter, parse_fields_params


def get_accounts_router(app) -> APIRouter:
    """Create and configure the accounts/auth API router."""
    router = APIRouter()
    fastapi_users = get_fast_api_users()
    current_active_verified_user = get_current_active_verified_user()
    current_active_verified_superuser = get_current_active_verified_superuser()
    pagination = Pagination(maximum_limit=100)

    router.include_router(
        fastapi_users.get_auth_router(
            auth_backend,
            # if is_verified=false response will be 400 Bad Request
            requires_verification=True,
        ),
        prefix="/auth/jwt",
        tags=["auth"],
    )

    @router.post(
        "/auth/jwt/refresh",
        tags=["auth"],
    )
    async def refresh_jwt(
        response: Response,
        account: Account = Depends(current_active_verified_user),
    ) -> dict[str, str]:
        """Generate a new JWT access token for the authenticated user."""
        return {"access_token": await get_jwt_strategy().write_token(account)}

    router.include_router(
        fastapi_users.get_register_router(AccountRead, AccountCreate),
        prefix="/auth",
        tags=["auth"],
    )

    router.include_router(
        fastapi_users.get_reset_password_router(),
        prefix="/auth",
        tags=["auth"],
    )

    router.include_router(
        fastapi_users.get_verify_router(AccountRead),
        prefix="/auth",
        tags=["auth"],
    )

    router.include_router(
        fastapi_users.get_users_router(AccountRead, AccountUpdate),
        prefix="/accounts",
        tags=["accounts"],
    )

    @router.get(
        "/accounts",
        response_description="List all accounts",
        tags=["accounts"],
        response_model=PaginatedAccounts,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def list_accounts(
        fields: Optional[FieldFilter] = Depends(parse_fields_params),
        pagination: Tuple[int, int, int] = Depends(pagination.parse_params),
        account: AccountRead = Depends(current_active_verified_superuser),
        database: SQLAlchemyUserDatabase = Depends(get_account_db),
    ) -> PaginatedResponse:
        """List all user accounts with pagination (superuser only)."""
        offset, limit, max_limit = pagination
        from_ = offset if offset else 0

        # TODO: Create and apply filter and sort functions.
        async with database.session as session:
            paginated_user_table = await session.execute(
                select(database.user_table).offset(from_).limit(limit)
            )
            account_entries = paginated_user_table.scalars().all()

        accounts = [
            AccountRead.model_validate(
                account_entry,
                from_attributes=True,  # Use from_attributes because we're validating from a SQLAlchemy model
            )
            for account_entry in account_entries
        ]

        return PaginatedAccounts.create(
            data=accounts,
            params=pagination,
        )

    return router
