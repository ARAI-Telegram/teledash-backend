import argparse
from typing import Optional

from elasticsearch.dsl import Q

from worker.database.database import Database


def clear_vectorized_indices(
    database: Database, chat_ids: Optional[list[int | str]] = None
):
    """Clear vectorized message indices."""
    if chat_ids:
        # Delete specific vectorized messages indices
        index_names = [f"vectorized_messages_{chat_id}" for chat_id in chat_ids]
        try:
            print(f"Deleting vectorized indices: {index_names}")
            database.es_client.indices.delete(
                index=index_names,
                ignore_unavailable=True,  # skip if doesn't exist
                allow_no_indices=True,  # don't error if none match
            )
            print(f"Vectorized indices deleted: {index_names}")
        except Exception as e:
            print(f"Error deleting vectorized indices {index_names}: {e}")
    else:
        # Delete all vectorized indices
        try:
            vec_indices = database.es_client.indices.get(index="vectorized_messages_*")
            if vec_indices:
                index_list = list(vec_indices.keys())
                print(f"Deleting all vectorized indices: {index_list}")
                database.es_client.indices.delete(
                    index=index_list, ignore_unavailable=True, allow_no_indices=True
                )
                print("All vectorized indices deleted.")
            else:
                print("No vectorized indices found.")
        except Exception as e:
            print(f"Error handling vectorized indices: {e}")


def clear_data(database: Database, chat_ids: Optional[list[int | str]] = None):
    """
    Deletes chats, messages, vectorized messages, and metrics for specified chat IDs.
    If no chat IDs are provided, data for all chats is deleted.
    """
    # Clear chats
    try:
        database.chats.delete(ids=chat_ids)
        print(f"Chats {chat_ids} cleared.")
    except Exception as e:
        print(f"Error clearing chats: {e}")
        return

    if chat_ids:
        # clear messages for specific chat IDs
        for chat_id in chat_ids:
            try:
                database.get_messages_collection(chat_id).delete()
                print(f"Messages for chat ID {chat_id} cleared.")
            except Exception as e:
                print(f"Error clearing messages for chat ID {chat_id}: {e}")
        # Clear metrics for specific chat IDs
        try:
            metrics_query = Q("terms", **{"metadata.chat_id": chat_ids})
            database.metrics.delete_by_query(query=metrics_query)
            print("Metrics for specified chats cleared.")
        except Exception as e:
            print(f"Error clearing metrics for chat IDs {chat_ids}: {e}")

    else:
        try:
            # Clear all messages indices
            message_indices = database.find_all_message_indices()
            for index in message_indices:
                try:
                    database.get_collection_by_name(index).delete()
                except Exception as e:
                    print(f"Error clearing messages index {index}: {e}")
            print("All messages cleared.")
        except Exception as e:
            print(f"Error finding message indices: {e}")

        try:
            # Clear all metrics
            database.metrics.delete()
            print("All metrics cleared.")
        except Exception as e:
            print(f"Error clearing all metrics: {e}")

    # Clear vectorized indices
    clear_vectorized_indices(database, chat_ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Delete messages, chats, and metrics for all or specific chat IDs."
    )
    parser.add_argument(
        "--chat-ids",
        nargs="*",  # Accept zero or more arguments
        type=int,
        help="Specific chat IDs to clear. If not provided, all chats will be cleared, including chats, messages, and metrics.",
    )

    args = parser.parse_args()
    database = Database()
    clear_data(database, chat_ids=args.chat_ids)
