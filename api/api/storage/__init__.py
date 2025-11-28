
from common.storage import Storage

storage = Storage(connect=False)


def get_storage() -> Storage:
    """Get storage instance for dependency injection."""
    return storage
