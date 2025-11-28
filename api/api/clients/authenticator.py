from datetime import datetime, timedelta
from typing import Dict, Optional, TypedDict

from pyrogram.client import Client as TelegramClient
from pyrogram.errors.exceptions import BadRequest
from pyrogram.errors.exceptions.unauthorized_401 import SessionPasswordNeeded
from pyrogram.types.authorization.sent_code import SentCode
from pyrogram.types.user_and_chats.user import User

from common.utils import naive_utcnow

# Full pyrogram error reference: https://docs.pyrogram.org/api/errors/

authenticator = None


class TwoFactorAuthenticationRequired(Exception):
    """
    Raised when phone code verification succeeds but 2FA/cloud password is required.
    """

    pass


class MapEntry(TypedDict):
    created_at: datetime
    tg_client: TelegramClient


class SignInResponse(TypedDict):
    user: User
    session_hash: str


class TelegramAuthenticator:
    """
    Handles Telegram authentication via phone.
    TODO: Doesn't scale because stored in memory.
    """

    map: Dict[str, MapEntry]

    def __init__(self) -> None:
        self.map = {}

    def get_client(self, client_id: str) -> MapEntry:
        return self.map[client_id]

    def has_client(self, client_id: str) -> bool:
        return client_id in self.map

    def add_client(self, client_id: str, tg_client: TelegramClient) -> None:
        self.map[client_id] = {"created_at": naive_utcnow(), "tg_client": tg_client}

    async def remove_client(self, client_id: str) -> None:
        if client_id not in self.map:
            return

        tg_client = self.map[client_id]["tg_client"]
        if tg_client.is_connected:
            await tg_client.disconnect()

        del self.map[client_id]

    async def remove_stale_clients(self) -> None:
        time_ago = naive_utcnow() - timedelta(minutes=30)
        ids_to_delete = [
            client_id
            for client_id, client in self.map.items()
            if client["created_at"] < time_ago
        ]
        [await self.remove_client(client_id) for client_id in ids_to_delete]

    async def start_auth(
        self,
        title: Optional[str],
        client_id: str,
        api_id: int,
        api_hash: str,
        phone_number: str,
        test_mode: bool = False,
    ) -> SentCode:
        """
        Start Telegram authentication process and send login
        code for specified phone number.
        """

        await self.remove_stale_clients()

        if self.has_client(client_id):
            await self.remove_client(client_id)

        tg_client = TelegramClient(
            name=str(api_id) + "." + title if title else str(api_id),
            api_id=api_id,
            api_hash=api_hash,
            phone_number=phone_number,
            test_mode=test_mode,
            no_updates=True,
            in_memory=True,
        )
        result = None
        await tg_client.connect()

        try:
            result = await tg_client.send_code(phone_number=phone_number)
        except BadRequest:
            if tg_client.is_connected:
                await tg_client.disconnect()

            raise ValueError("Phone number is invalid")

        self.add_client(client_id, tg_client)

        return result

    async def verify_phone_code(
        self,
        client_id: str,
        phone_number: str,
        phone_code_hash: str,
        phone_code: str,
    ) -> SignInResponse:
        """
        Verify phone code and complete authentication if no 2FA/cloud password is required.

        Args:
            client_id: The client identifier
            phone_number: Phone number used for authentication
            phone_code_hash: Hash received from start_auth
            phone_code: Verification code sent to device or authenticated client

        Returns:
            SignInResponse with user and session_hash

        Raises:
            TwoFactorAuthenticationRequired: When 2FA/cloud password is needed
            ValueError: When phone code is invalid
            NotImplementedError: When phone number is not registered or user needs to accept Terms of Service
            Exception: When session not found or expired or other authentication errors
        """

        if not self.has_client(client_id):
            raise Exception(
                f"Session for client {client_id} not created. Please restart authentication process."
            )

        tg_client = self.get_client(client_id)["tg_client"]

        try:
            # Try to sign in with phone code
            user = await tg_client.sign_in(
                phone_number=phone_number,
                phone_code_hash=phone_code_hash,
                phone_code=phone_code,
            )

            # If no User instance is returned, the phone number is either not
            # registered or the user needs to accept the Terms of Services. Both
            # is not implemented.
            # See https://docs.kurigram.live/api/methods/sign_in/
            if not isinstance(user, User):
                raise NotImplementedError(
                    "Authorization failed. Phone number is not registered or the user needs to accept the Terms of Services."
                )

            # Authentication completed without 2FA
            session_hash = await tg_client.export_session_string()
            await tg_client.disconnect()

            # Remove client from list
            await self.remove_client(client_id)

            return {
                "user": user,
                "session_hash": session_hash,
            }

        except BadRequest:
            # Telegram API returns more specific error messages, Kurigram does not.
            raise ValueError("Phone code is invalid or expired")
        except SessionPasswordNeeded:
            raise TwoFactorAuthenticationRequired(
                f"Two-factor authentication is enabled for phone number {phone_number}. Please provide your 2FA/cloud password."
            )

    async def verify_password(
        self,
        client_id: str,
        password: str,
    ) -> SignInResponse:
        """
        Verify 2FA/cloud password and complete authentication.
        Needs to be called after verify_phone_code returned requires_password=True.
        Requires an active client session.

        Args:
            client_id: The client identifier
            password: 2FA/cloud password
        Returns:
            SignInResponse with user and session_hash
        """

        if not self.has_client(client_id):
            raise Exception(
                f"Session for client {client_id} not found or expired. Please restart authentication process."
            )

        tg_client = self.get_client(client_id)["tg_client"]

        try:
            user = await tg_client.check_password(password=password)
            session_hash = await tg_client.export_session_string()
            await tg_client.disconnect()

            # Remove client from list
            await self.remove_client(client_id)

            return {"user": user, "session_hash": session_hash}

        except BadRequest:
            raise ValueError("Invalid password")


def get_authenticator() -> TelegramAuthenticator:
    """Get Telegram authenticator instance for dependency injection."""
    global authenticator

    if not authenticator:
        authenticator = TelegramAuthenticator()

    return authenticator
