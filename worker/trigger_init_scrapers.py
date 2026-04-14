import argparse

from worker.database.database import Database
from worker.tasks import init_scrapers


def run_init_scrapers():
    init_scrapers.delay()
    print("Triggering init_scrapers task...")


def clear_collections(database):
    # Clear the chats collection
    database.chats.delete()
    print("Chats collection cleared.")

    # Clear the messages collection
    # Get all message indices (e.g., messages_* indices)
    message_indices = database.find_all_message_indices()

    for index in message_indices:
        database.get_collection_by_name(index).delete()
    print("Messages collections cleared.")
    # TODO: remove also all vectorized indices?

    # Clear the metrics collection
    database.metrics.delete()
    print("Metrics collection cleared.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Initialize scrapers and optionally clear database collections."
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear database collections before initializing scrapers.",
    )  # when running the script with flag --clear, the db collections get cleared

    args = parser.parse_args()

    database = Database()

    if args.clear:
        clear_collections(database)

    run_init_scrapers()
