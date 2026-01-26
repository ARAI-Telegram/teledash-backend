"""
Shared test fixtures for API tests.

Testing patterns:
- Unit tests: Fast, isolated, fully mocked
- Integration tests: Slower, use real backends
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.accounts.auth import Account
from api.database.database import (
    ChatsCollection,
    ClientsCollection,
    Database,
    MessagesCollection,
    MetricsCollection,
    UpdateTargetNotFoundError,
    UsersCollection,
)
from common.database.models.chat import ChatOut, ChatType
from common.database.models.client import ClientOut
from common.database.models.message import MessageOut
from common.database.models.user import UserOut

# =============================================================================
# Mock Account Fixtures
# =============================================================================


@pytest.fixture
def mock_account():
    """Create a mock authenticated account for testing."""
    account = Mock(spec=Account)
    account.id = uuid.uuid4()
    account.email = "test@example.com"
    account.is_active = True
    account.is_verified = True
    account.is_superuser = False
    account.first_name = "Test"
    account.last_name = "User"
    account.hashed_password = "hashed_password"
    return account


@pytest.fixture
def mock_superuser_account():
    """Create a mock superuser account for testing."""
    account = Mock(spec=Account)
    account.id = uuid.uuid4()
    account.email = "admin@example.com"
    account.is_active = True
    account.is_verified = True
    account.is_superuser = True
    account.first_name = "Admin"
    account.last_name = "User"
    account.hashed_password = "hashed_password"
    return account


# =============================================================================
# Mock Elasticsearch Client Fixtures
# =============================================================================


@pytest.fixture
def mock_es_client():
    """Create a mock AsyncElasticsearch client."""
    mock_client = AsyncMock()

    # Mock common methods
    mock_client.search = AsyncMock(
        return_value={"hits": {"hits": [], "total": {"value": 0}}, "aggregations": {}}
    )
    mock_client.index = AsyncMock(return_value={"_id": "test_id", "result": "created"})
    mock_client.update = AsyncMock(return_value={"result": "updated"})
    mock_client.delete = AsyncMock(return_value={"result": "deleted"})
    mock_client.count = AsyncMock(return_value={"count": 0})
    mock_client.indices = AsyncMock()
    mock_client.indices.get_mapping = AsyncMock(return_value={})
    mock_client.close = AsyncMock()

    return mock_client


# =============================================================================
# Mock Database Fixtures
# =============================================================================


@pytest.fixture
def mock_database(mock_es_client):
    """Create a mock Database instance with mocked collections."""
    with patch("api.database.database.AsyncElasticsearch") as mock_es_class:
        mock_es_class.return_value = mock_es_client

        db = Database(connect=False)
        db.es_client = mock_es_client

        # Create mock collections
        db.clients = MagicMock(spec=ClientsCollection)
        db.chats = MagicMock(spec=ChatsCollection)
        db.messages = MagicMock(spec=MessagesCollection)
        db.users = MagicMock(spec=UsersCollection)
        db.metrics = MagicMock(spec=MetricsCollection)

        # Set up async mock methods for each collection
        for collection in [db.clients, db.chats, db.messages, db.users, db.metrics]:
            collection.find = AsyncMock(return_value=async_generator([]))
            collection.find_one = AsyncMock(return_value=None)
            collection.count = AsyncMock(return_value=0)
            collection.insert_one = AsyncMock(return_value="test_id")
            collection.update_one = AsyncMock(
                side_effect=UpdateTargetNotFoundError("No document found")
            )
            collection.delete_by_id = AsyncMock(return_value=None)
            collection.delete_by_query = AsyncMock()
            collection.bulk_write = AsyncMock(return_value=(0, []))
            collection.get_top_field_values = AsyncMock(return_value=[])

        yield db


async def async_generator(items):
    """Helper to create an async generator from a list."""
    for item in items:
        yield item


# =============================================================================
# Sample Data Factories
# =============================================================================


@pytest.fixture
def sample_chat():
    """Create a sample ChatOut for testing."""
    return ChatOut(
        id=123456789,
        type=ChatType.CHANNEL,
        title="Test Channel",
        username="test_channel",
        description="A test channel for unit tests",
        members_count=1000,
        scraped_by="test_client_id",
        added_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )


@pytest.fixture
def sample_chat_list(sample_chat):
    """Create a list of sample chats for testing."""
    chats = [sample_chat]
    for i in range(1, 5):
        chats.append(
            ChatOut(
                id=123456789 + i,
                type=ChatType.CHANNEL if i % 2 == 0 else ChatType.SUPERGROUP,
                title=f"Test Channel {i}",
                username=f"test_channel_{i}",
                description=f"Test channel {i} description",
                members_count=1000 * i,
                scraped_by="test_client_id",
                added_at=datetime(2024, 1, 1, 0, 0, 0),
                updated_at=datetime(2024, 1, 1, 0, 0, 0),
            )
        )
    return chats


@pytest.fixture
def sample_client():
    """Create a sample ClientOut for testing."""
    return ClientOut(
        id="test_client_id",
        phone_number="+1234567890",
        api_id=12345,
        api_hash="test_api_hash",
        is_active=True,
        chats=[],
    )


@pytest.fixture
def sample_message():
    """Create a sample MessageOut for testing."""
    return MessageOut(
        id=1,
        chat_id=123456789,
        date=datetime(2024, 1, 1, 12, 0, 0),
        text="This is a test message",
        views=100,
    )


@pytest.fixture
def sample_user():
    """Create a sample UserOut for testing."""
    return UserOut(
        id=987654321,
        first_name="Test",
        last_name="User",
        username="testuser",
    )


# =============================================================================
# FastAPI Test Client Fixtures
# =============================================================================


@pytest.fixture
def mock_app(mock_database, mock_account):
    """Create a FastAPI app with mocked dependencies for testing."""
    from api.main import app

    # Override the database dependency
    async def get_mock_database():
        return mock_database

    # Override the authentication dependency

    # Store original dependencies
    from api.database import get_database

    app.dependency_overrides[get_database] = get_mock_database

    # We need to override the dependency returned by get_current_active_verified_user
    # This is tricky because it returns a dependency function

    yield app

    # Cleanup
    app.dependency_overrides.clear()


@pytest.fixture
async def async_client(mock_app):
    """Create an async HTTP client for testing FastAPI endpoints."""
    async with AsyncClient(
        transport=ASGITransport(app=mock_app), base_url="http://test"
    ) as client:
        yield client


# =============================================================================
# Elasticsearch Response Mocks
# =============================================================================


@pytest.fixture
def mock_es_search_response():
    """Create a mock Elasticsearch search response."""

    def _create_response(hits=None, total=0, aggregations=None):
        if hits is None:
            hits = []

        response = MagicMock()
        response.hits = []

        for hit_data in hits:
            hit = MagicMock()
            hit.to_dict.return_value = hit_data
            hit.meta.id = hit_data.get("id", str(uuid.uuid4()))
            hit.meta.score = hit_data.get("score", 1.0)
            if "highlight" in hit_data:
                hit.meta.highlight.to_dict.return_value = hit_data["highlight"]
            else:
                del hit.meta.highlight
            response.hits.append(hit)

        if aggregations:
            response.aggregations = MagicMock()
            for key, value in aggregations.items():
                setattr(response.aggregations, key, value)

        return response

    return _create_response


# =============================================================================
# Environment Variable Isolation
# =============================================================================


@pytest.fixture(autouse=True)
def isolate_env_vars():
    """
    Isolate environment variables for each test to prevent test interference.

    This fixture automatically backs up a set of environment variables before each test,
    and restores their original values after the test completes. This ensures that changes
    to environment variables in one test do not affect other tests, maintaining test isolation.
    The variables managed include ES_HOST, ES_PORT, ES_SCHEME, STORAGE_PROVIDER, STORAGE_ENDPOINT,
    STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY, JWT_SECRET, and JWT_LIFETIME_SECONDS.
    """
    import os

    # Backup relevant env vars
    env_backup = {}
    test_env_vars = [
        "ES_HOST",
        "ES_PORT",
        "ES_SCHEME",
        "STORAGE_PROVIDER",
        "STORAGE_ENDPOINT",
        "STORAGE_ACCESS_KEY",
        "STORAGE_SECRET_KEY",
        "JWT_SECRET",
        "JWT_LIFETIME_SECONDS",
    ]

    for var in test_env_vars:
        if var in os.environ:
            env_backup[var] = os.environ[var]

    yield

    # Restore env vars
    for var, value in env_backup.items():
        os.environ[var] = value
    # Remove any new env vars that were added during the test
    for var in test_env_vars:
        if var not in env_backup and var in os.environ:
            del os.environ[var]
