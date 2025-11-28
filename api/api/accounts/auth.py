import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Optional, Union
from uuid import uuid4

from fastapi import Depends, Request
from fastapi_users import UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from fastapi_users.exceptions import InvalidPasswordException
from fastapi_users.fastapi_users import FastAPIUsers
from fastapi_users.manager import BaseUserManager
from sqlalchemy import JSON, Column, DateTime, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import DeclarativeBase

from api.accounts.models import AccountCreate, AccountRead
from common.settings import settings
from common.utils import naive_utcnow

logger = logging.getLogger(__name__)

DATABASE_URL = "sqlite+aiosqlite:///./data/accounts.db"


class Base(DeclarativeBase):
    pass


class Account(Base, SQLAlchemyBaseUserTableUUID):
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    clients = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=naive_utcnow())
    updated_at = Column(DateTime, nullable=False, default=naive_utcnow())
    saved_searches = Column(
        JSON, nullable=True
    )  # setting this to JSON parses it into a dict when reading from the database


class AccountManager(UUIDIDMixin, BaseUserManager[Account, uuid.UUID]):
    reset_password_token_secret = settings.jwt_secret
    verification_token_secret = settings.jwt_secret

    async def on_after_register(
        self, account: Account, request: Optional[Request] = None
    ):
        logger.info(f"Account {account.id} has registered.")

    async def on_after_forgot_password(
        self, account: Account, token: str, request: Optional[Request] = None
    ):
        logger.info(f"Account {account.id} has forgot their password.")

    async def on_after_request_verify(
        self, account: Account, token: str, request: Optional[Request] = None
    ):
        logger.info(f"Verification requested for account {account.id}.")

    async def validate_password(
        self,
        password: str,
        user: Union[AccountCreate, AccountRead],
    ) -> None:
        if len(password) < 8:
            raise InvalidPasswordException(
                reason="Password should be at least 8 characters."
            )
        if user.email in password:
            raise InvalidPasswordException(
                reason="Password should not contain the e-mail address."
            )


engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def create_accounts_db_and_table() -> None:
    """Create accounts database tables and insert default superuser if empty."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await insert_superuser_if_empty()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Get async SQLAlchemy session for dependency injection."""
    async with async_session_maker() as session:
        yield session


async def insert_superuser_if_empty() -> None:
    """Insert default admin account if accounts table is empty."""
    async with async_session_maker() as session:
        # Check if the accounts table is empty
        result = await session.execute(select(Account))
        accounts = result.scalars().all()

        if not accounts:
            # Define the default user
            current_time = naive_utcnow()
            default_user = Account(
                id=str(uuid4()),
                email="admin@example.com",
                is_active=True,
                is_superuser=True,
                is_verified=True,
                hashed_password="$2b$12$LuqZ828H/CJY90kTANEaxuDNLSw4WEeJoSPlvJzSsOoI9x7uHVzQa",
                first_name="Admin",
                last_name="",
                created_at=current_time,
                updated_at=current_time,
            )
            session.add(default_user)
            await session.commit()


def get_jwt_strategy() -> JWTStrategy[Account, uuid.UUID]:
    """Get JWT authentication strategy for FastAPI Users."""
    return JWTStrategy(
        secret=settings.jwt_secret, lifetime_seconds=settings.jwt_lifetime_seconds
    )


fastapi_users = None
bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)


async def get_account_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, Account)


def get_account_manager(
    account_db: SQLAlchemyUserDatabase = Depends(get_account_db),
) -> AccountManager:
    return AccountManager(account_db)


def init_fast_api_users() -> None:
    """Initialize FastAPI Users instance with authentication backend."""
    global fastapi_users
    fastapi_users = FastAPIUsers[Account, uuid.UUID](
        get_account_manager, [auth_backend]
    )


def get_fast_api_users() -> FastAPIUsers:
    """Get initialized FastAPI Users instance."""
    if fastapi_users is None:
        raise ValueError("Database is not initialized")

    return fastapi_users


def get_current_active_verified_user():
    """Dependency to get current active and verified user."""
    return get_fast_api_users().current_user(active=True, verified=True)


def get_current_active_verified_superuser():
    """Dependency to get current active, verified superuser."""
    return get_fast_api_users().current_user(active=True, verified=True, superuser=True)
