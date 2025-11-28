from enum import Enum
from typing import List, Optional, Tuple, cast

from pydantic import BaseModel, ValidationError
from pyrogram import types as pyrogram_types

from common.database.models.refs import UserRef
from common.database.models.user import User
from common.utils import serialize_pyrogram_type


class MessageServiceType(str, Enum):
    """Message service type enumeration compatible with Pydantic."""

    UNSUPPORTED = "UNSUPPORTED"
    """A message content that is not supported in the current pyrogram version"""

    CUSTOM_ACTION = "CUSTOM_ACTION"
    """Custom action"""

    NEW_CHAT_MEMBERS = "NEW_CHAT_MEMBERS"
    """New members join"""

    LEFT_CHAT_MEMBER = "LEFT_CHAT_MEMBER"
    """Left chat member"""

    NEW_CHAT_TITLE = "NEW_CHAT_TITLE"
    """New chat title"""

    NEW_CHAT_PHOTO = "NEW_CHAT_PHOTO"
    """New chat photo"""

    DELETE_CHAT_PHOTO = "DELETE_CHAT_PHOTO"
    """Deleted chat photo"""

    FORUM_TOPIC_CREATED = "FORUM_TOPIC_CREATED"
    """A new forum topic created in the chat"""

    FORUM_TOPIC_CLOSED = "FORUM_TOPIC_CLOSED"
    """A new forum topic closed in the chat"""

    FORUM_TOPIC_REOPENED = "FORUM_TOPIC_REOPENED"
    """A new forum topic reopened in the chat"""

    FORUM_TOPIC_EDITED = "FORUM_TOPIC_EDITED"
    """A new forum topic renamed in the chat"""

    GENERAL_FORUM_TOPIC_HIDDEN = "GENERAL_FORUM_TOPIC_HIDDEN"
    """A general forum topic hidden in the chat"""

    GENERAL_FORUM_TOPIC_UNHIDDEN = "GENERAL_FORUM_TOPIC_UNHIDDEN"
    """A general forum topic unhidden in the chat"""

    GROUP_CHAT_CREATED = "GROUP_CHAT_CREATED"
    """Group chat created"""

    CHANNEL_CHAT_CREATED = "CHANNEL_CHAT_CREATED"
    """Channel chat created"""

    SUPERGROUP_CHAT_CREATED = "SUPERGROUP_CHAT_CREATED"
    """Supergroup chat created"""

    MIGRATE_TO_CHAT_ID = "MIGRATE_TO_CHAT_ID"
    """Migrated to chat id"""

    MIGRATE_FROM_CHAT_ID = "MIGRATE_FROM_CHAT_ID"
    """Migrated from chat id"""

    PINNED_MESSAGE = "PINNED_MESSAGE"
    """Pinned message"""

    GAME_HIGH_SCORE = "GAME_HIGH_SCORE"
    """Game high score"""

    GIVEAWAY_CREATED = "GIVEAWAY_CREATED"
    """Giveaway created"""

    GIVEAWAY_COMPLETED = "GIVEAWAY_COMPLETED"
    """Giveaway completed"""

    GIFT_CODE = "GIFT_CODE"
    """Gift code"""

    GIFTED_PREMIUM = "GIFTED_PREMIUM"
    """Gifted Telegram Premium"""

    GIFTED_STARS = "GIFTED_STARS"
    """Gifted stars"""

    GIFTED_TON = "GIFTED_TON"
    """Gifted TON"""

    VIDEO_CHAT_STARTED = "VIDEO_CHAT_STARTED"
    """Video chat started"""

    VIDEO_CHAT_ENDED = "VIDEO_CHAT_ENDED"
    """Video chat ended"""

    VIDEO_CHAT_SCHEDULED = "VIDEO_CHAT_SCHEDULED"
    """Video chat scheduled"""

    VIDEO_CHAT_MEMBERS_INVITED = "VIDEO_CHAT_MEMBERS_INVITED"
    """Video chat members invited"""

    PHONE_CALL_STARTED = "PHONE_CALL_STARTED"
    """Phone call started"""

    PHONE_CALL_ENDED = "PHONE_CALL_ENDED"
    """Phone call ended"""

    WEB_APP_DATA = "WEB_APP_DATA"
    """Web app data"""

    USERS_SHARED = "USERS_SHARED"
    """Requested users"""

    CHAT_SHARED = "CHAT_SHARED"
    """Requested chat"""

    SUCCESSFUL_PAYMENT = "SUCCESSFUL_PAYMENT"
    """Successful payment"""

    REFUNDED_PAYMENT = "REFUNDED_PAYMENT"
    """Refunded payment"""

    SUGGESTED_POST_APPROVAL_FAILED = "SUGGESTED_POST_APPROVAL_FAILED"
    """Suggested post approval failed"""

    SUGGESTED_POST_APPROVED = "SUGGESTED_POST_APPROVED"
    """Suggested post approved"""

    SUGGESTED_POST_DECLINED = "SUGGESTED_POST_DECLINED"
    """Suggested post declined"""

    SUGGESTED_POST_PAID = "SUGGESTED_POST_PAID"
    """Suggested post paid"""

    SUGGESTED_POST_REFUNDED = "SUGGESTED_POST_REFUNDED"
    """Suggested post refunded"""

    SET_MESSAGE_AUTO_DELETE_TIME = "SET_MESSAGE_AUTO_DELETE_TIME"
    """Chat TTL changed"""

    CHAT_BOOST = "CHAT_BOOST"
    """Boost applied to the chat"""

    GIFT = "GIFT"
    """Star gift"""

    CONNECTED_WEBSITE = "CONNECTED_WEBSITE"
    """Connected website"""

    WRITE_ACCESS_ALLOWED = "WRITE_ACCESS_ALLOWED"
    """Write access allowed"""

    SCREENSHOT_TAKEN = "SCREENSHOT_TAKEN"
    """Screenshot taken"""

    CONTACT_REGISTERED = "CONTACT_REGISTERED"
    """Contact registered"""

    PROXIMITY_ALERT_TRIGGERED = "PROXIMITY_ALERT_TRIGGERED"
    """Proximity alert triggered"""

    HISTORY_CLEARED = "HISTORY_CLEARED"
    """Chat history cleared"""

    SUGGEST_PROFILE_PHOTO = "SUGGEST_PROFILE_PHOTO"
    """Suggest profile photo"""

    SUGGEST_BIRTHDAY = "SUGGEST_BIRTHDAY"
    """Suggest birthday"""

    CHAT_SET_BACKGROUND = "CHAT_SET_BACKGROUND"
    """Set chat background"""

    CHAT_SET_THEME = "CHAT_SET_THEME"
    """Set chat theme"""

    GIVEAWAY_PRIZE_STARS = "GIVEAWAY_PRIZE_STARS"
    """Giveaway prize stars"""

    PAID_MESSAGES_REFUNDED = "PAID_MESSAGES_REFUNDED"
    """Refunded paid messages"""

    PAID_MESSAGES_PRICE_CHANGED = "PAID_MESSAGES_PRICE_CHANGED"
    """Paid messages price"""

    DIRECT_MESSAGE_PRICE_CHANGED = "DIRECT_MESSAGE_PRICE_CHANGED"
    """Direct message price"""

    CHECKLIST_TASKS_DONE = "CHECKLIST_TASKS_DONE"
    """Checklist tasks done"""

    CHECKLIST_TASKS_ADDED = "CHECKLIST_TASKS_ADDED"
    """Checklist tasks added"""


class MessageServiceInfo(BaseModel):
    service_type: Optional[MessageServiceType] = None
    new_chat_members: Optional[List[UserRef]] = None
    left_chat_member: Optional[UserRef] = None
    new_chat_title: Optional[str] = None
    new_chat_photo: Optional[dict] = None  # TODO: pyrogram_types.Photo
    delete_chat_photo: Optional[bool] = None
    group_chat_created: Optional[bool] = None
    supergroup_chat_created: Optional[bool] = None
    channel_chat_created: Optional[bool] = None
    migrate_to_chat_id: Optional[int] = None
    migrate_from_chat_id: Optional[int] = None
    pinned_message_id: Optional[int] = None
    history_cleared: Optional[bool] = None
    set_message_auto_delete_time: Optional[int] = None
    screenshot_taken: Optional[bool] = None
    proximity_alert_triggered: Optional[bool] = None

    @classmethod
    def from_pyrogram_message(
        cls, message: pyrogram_types.Message, client_id: str
    ) -> Tuple[List[User], Optional["MessageServiceInfo"]]:
        # wanted_service_types = { # TODO: currently not used
        #     pyrogram_service_types.NEW_CHAT_MEMBERS,
        #     pyrogram_service_types.LEFT_CHAT_MEMBER,
        #     pyrogram_service_types.NEW_CHAT_TITLE,
        #     pyrogram_service_types.NEW_CHAT_PHOTO,
        #     pyrogram_service_types.DELETE_CHAT_PHOTO,
        #     pyrogram_service_types.GROUP_CHAT_CREATED,
        #     pyrogram_service_types.SUPERGROUP_CHAT_CREATED,
        #     pyrogram_service_types.CHANNEL_CHAT_CREATED,
        #     pyrogram_service_types.MIGRATE_TO_CHAT_ID,
        #     pyrogram_service_types.MIGRATE_FROM_CHAT_ID,
        #     pyrogram_service_types.PINNED_MESSAGE,
        #     pyrogram_service_types.HISTORY_CLEARED,
        #     pyrogram_service_types.SET_MESSAGE_AUTO_DELETE_TIME,
        #     pyrogram_service_types.SCREENSHOT_TAKEN,
        #     pyrogram_service_types.PROXIMITY_ALERT_TRIGGERED,
        # }

        if not message.service:  # or message.service not in wanted_service_types:
            return [], None

        service_type = message.service
        new_users = []

        # Convert pyrogram service type to our enum
        converted_service_type = None
        if service_type:
            # Try to get the string representation of the service type
            try:
                converted_service_type = MessageServiceType(service_type.name)
            except ValueError:
                # If the service type is not in our enum, use UNSUPPORTED
                converted_service_type = MessageServiceType.UNSUPPORTED

        try:
            new_chat_members = (
                [
                    User.from_pyrogram_user(user, client_id)
                    for user in message.new_chat_members
                ]
                if message.new_chat_members
                else None
            )
            left_chat_member = (
                User.from_pyrogram_user(message.left_chat_member, client_id)
                if message.left_chat_member
                else None
            )
        except ValidationError:
            raise ValueError(f'Error validating users in service info ("{message.id}")')

        if new_chat_members:
            new_users = new_chat_members

        if left_chat_member:
            new_users.append(left_chat_member)

        service_info = cls(
            service_type=converted_service_type,
            new_chat_members=(
                [user.create_ref() for user in new_chat_members]
                if new_chat_members
                else None
            ),
            left_chat_member=(
                left_chat_member.create_ref() if left_chat_member else None
            ),
            new_chat_title=message.new_chat_title,
            new_chat_photo=cast(
                Optional[dict], serialize_pyrogram_type(message.new_chat_photo)
            ),
            delete_chat_photo=message.delete_chat_photo,
            group_chat_created=message.group_chat_created,
            supergroup_chat_created=message.supergroup_chat_created,
            channel_chat_created=message.channel_chat_created,
            migrate_to_chat_id=message.migrate_to_chat_id,
            migrate_from_chat_id=message.migrate_from_chat_id,
            pinned_message_id=(
                message.pinned_message.id if message.pinned_message else None
            ),
            history_cleared=True if message.history_cleared else None,
            set_message_auto_delete_time=message.set_message_auto_delete_time,
            screenshot_taken=True if message.screenshot_taken else None,
            proximity_alert_triggered=True
            if message.proximity_alert_triggered
            else None,
        )

        return new_users, service_info
