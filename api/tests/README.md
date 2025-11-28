# API Tests

This directory contains comprehensive tests for the Teledash API endpoints, database operations, and validators.

## Installation

Install test dependencies inside the Docker container:

```bash
docker exec api pip install -r common/requirements.test.txt
```

## Running Tests

Tests should be run inside the Docker container:

```bash
docker exec api python3 -m pytest tests/ -v
```

Or if running locally with the correct Python environment:

```bash
python3 -m pytest api/tests/ -v
```

### Run Only Unit Tests (Fast)

```bash
docker exec api python3 -m pytest tests/unit/ -v
```

### Run Only Integration Tests

Integration tests require a running Elasticsearch instance and proper `.env` configuration.

```bash
docker exec api python3 -m pytest tests/integration/ -v
```

### Run Specific Test File

```bash
docker exec api python3 -m pytest tests/unit/test_validators.py -v
```

### Run Specific Test Class or Method

```bash
# Run a test class
docker exec api python3 -m pytest tests/unit/test_chats.py::TestChatFiltering -v

# Run a specific test
docker exec api python3 -m pytest tests/unit/test_validators.py::TestParseSortParams::test_default_chat_sort_no_params -v
```

### Run with Coverage

```bash
docker exec api python3 -m pytest tests/ -v --cov=api --cov-report=html
```

This will generate an HTML coverage report in `htmlcov/index.html`.

## Writing New Tests

### Unit Tests

Unit tests should:

- Use mocked database and Elasticsearch client (see `conftest.py` fixtures)
- Be fast and isolated
- Not require external dependencies
- Test individual methods and logic

Example:

```python
from unittest.mock import AsyncMock, patch

class TestMyFeature:
    @pytest.mark.asyncio
    async def test_database_operation(self, mock_database):
        # Configure mock
        mock_database.chats.find_one = AsyncMock(return_value=sample_chat)

        # Test implementation
        result = await mock_database.chats.find_one(filter=Q("ids", values=["123"]))
        assert result is not None

    def test_validator(self):
        from api.chats.validators import parse_chat_filter

        result = parse_chat_filter(type=ChatType.CHANNEL, tags=None)
        assert result is not None
```

### Integration Tests

Integration tests should:

- Use real Elasticsearch backend
- Have proper cleanup (try/finally)
- Use UUID for unique test resource names
- Run inside Docker container

Example:

```python
class TestAPIIntegration:
    @pytest.fixture
    def test_client(self):
        # Set up test client
        pass

    def test_endpoint(self, test_client):
        # Test with real backend
        response = test_client.get("/chats")
        assert response.status_code == 200
```

### Async Tests

For async tests, use the `@pytest.mark.asyncio` decorator and ensure `pytest-asyncio` is installed:

```python
import pytest

@pytest.mark.asyncio
async def test_async_operation(self, mock_database):
    result = await mock_database.chats.count()
    assert result == 0
```

## Testing Patterns

1. **Separate unit and integration tests** into different directories
2. **Mock external dependencies** (Elasticsearch, authentication) in unit tests
3. **Test error scenarios** with appropriate mocks
4. **Use environment variable isolation** to prevent test interference
5. **Always cleanup** in integration tests with try/finally
6. **Use UUIDs** for unique test resource names
