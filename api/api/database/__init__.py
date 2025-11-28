from api.database.database import Database

database = Database(connect=False)


async def get_database() -> Database:
    """Get database instance for dependency injection."""
    return database
