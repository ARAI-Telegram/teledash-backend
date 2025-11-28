from typing import Optional

from elasticsearch.dsl import Q

from api.database.database import Database
from common.database.models.client import Client


async def get_username_for_chat_id(chat_id: int, database: Database) -> Optional[str]:
    """
    Finds the username associated with a given chat ID.

    This function searches for a chat username in two places:
    1. In the `similar_channels` field of the `chats` collection. And, if not successfull here:
    2. In the `forward.from_chat` field of the `messages` collection.

    Args:
        chat_id (int): The ID of the chat to search for.
        database (Database): The database instance to use for querying.

    Returns:
        Optional[str]: The username associated with the given chat ID, or None if not found.
    """
    filter_query = Q("bool", filter=[Q("term", **{"similar_channels.id": chat_id})])
    chat_doc = await database.chats.find_one(
        filter=filter_query, fields={"includes": ["similar_channels"]}
    )
    if chat_doc and chat_doc.similar_channels:
        for channel in chat_doc.similar_channels:
            channel_id = channel.id
            if channel_id == chat_id:
                username = channel.username
                return username

    # if no username was found so far: check in forwards
    filter_query = Q("term", **{"forward.from_chat.id": chat_id})
    message_doc = await database.messages.find_one(
        filter=filter_query,
        fields={"includes": ["forward"]},
    )

    if message_doc:
        forward_message = message_doc.forward
        if forward_message and forward_message.from_chat:
            username_forward = forward_message.from_chat.username
            if username_forward:
                return username_forward

    return None


async def assign_chat_username_to_client(
    client: Client, username: str, database: Database
) -> str:
    """
    Assigns a chat username to a client by updating the client's record in the database.

    Args:
        client (Client): The client object to which the chat username will be assigned.
        username (str): The chat username to be assigned to the client.
        database (Database): The database object used to update the client's record.

    Returns:
        str: A status message indicating the result of the operation. Possible values are:
            - "ALREADY_EXISTS": The username is already in the client's list of chats to join.
            - "SUCCESS": The username was successfully added and the client's record was updated.
            - "UPDATE_FAILED": The update operation failed.
    """
    chats_to_join = client.chats_to_join if client.chats_to_join else []

    if username in chats_to_join:
        return "ALREADY_EXISTS"

    chats_to_join.append(str(username))

    update_query = {"chats_to_join": chats_to_join}
    filter = Q("ids", values=[str(client.id)])
    updated_doc = await database.clients.update_one(query=filter, update=update_query)

    if updated_doc:
        return "SUCCESS"
    else:
        return "UPDATE_FAILED"
