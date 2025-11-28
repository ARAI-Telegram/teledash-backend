import asyncio

import pytest
import pytest_asyncio

try:
    from api.database.database import Database

    IS_ASYNC = True
except ModuleNotFoundError:
    from worker.database.database import Database

    IS_ASYNC = False


if IS_ASYNC:

    @pytest.fixture(scope="module")
    def event_loop():
        """Create an instance of the default event loop for the test module."""
        policy = asyncio.get_event_loop_policy()
        loop = policy.new_event_loop()
        yield loop
        loop.close()


@pytest_asyncio.fixture(scope="module")
async def db_instance():
    """Fixture to provide a Database instance."""
    db = Database()
    yield db
    if IS_ASYNC:
        await db.close()
    else:
        db.close()


@pytest_asyncio.fixture(scope="module")
async def es_client(db_instance):
    """Fixture to provide a connected Elasticsearch client."""
    return db_instance.es_client


@pytest_asyncio.fixture(scope="module")
async def es_db(db_instance):
    """Fixture to provide an Elasticsearch Database object."""
    return db_instance


@pytest.mark.asyncio(loop_scope="module")
async def test_elasticsearch_connection(es_client):
    """Test connection to Elasticsearch by checking cluster health."""
    print("Connection to Elasticsearch verified successfully.")
    if IS_ASYNC:
        health = await es_client.cluster.health()
    else:
        health = es_client.cluster.health()
    assert health["status"] in {"green", "yellow", "red"}
    print(f"Cluster Health: {health}")


@pytest.mark.asyncio(loop_scope="module")
async def test_mandatory_indices_exist(es_client):
    """Test that the index 'clients' exists in Elasticsearch. Otherwise no scraping can succeed."""
    if IS_ASYNC:
        client_exists = await es_client.indices.exists(index="clients")
        chats_exists = await es_client.indices.exists(index="chats")
        messages_exists = await es_client.indices.exists(index="messages")
        users_exists = await es_client.indices.exists(index="users")
    else:
        client_exists = es_client.indices.exists(index="clients")
        chats_exists = es_client.indices.exists(index="chats")
        messages_exists = es_client.indices.exists(index="messages")
        users_exists = es_client.indices.exists(index="users")
    assert client_exists, "Index 'clients' does not exist."
    assert chats_exists, "Index 'chats' does not exist."
    assert messages_exists, "Index 'messages' does not exist."
    assert users_exists, "Index 'users' does not exist."
