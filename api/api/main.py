import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.accounts.auth import create_accounts_db_and_table, init_fast_api_users
from api.accounts.routes import get_accounts_router
from api.chats.routes import get_chats_router
from api.clients.routes import get_clients_router
from api.database import database
from api.labeling.routes import get_labeling_router
from api.messages.routes import get_messages_router
from api.metrics.routes import get_metrics_router
from api.saved_searches.routes import get_saved_searches_router
from api.storage import storage
from api.storage.routes import get_storage_router
from api.tags.routes import get_tags_router
from api.users.routes import get_users_router
from common.settings import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle."""
    # Startup
    database.connect()

    await create_accounts_db_and_table()

    init_fast_api_users()
    app.include_router(get_accounts_router(app))
    app.include_router(get_messages_router(app))
    app.include_router(get_clients_router(app))
    app.include_router(get_chats_router(app))
    app.include_router(get_users_router(app))
    app.include_router(get_metrics_router(app))
    app.include_router(get_saved_searches_router())
    app.include_router(get_tags_router())
    app.include_router(get_labeling_router())

    if settings.storage_endpoint and len(settings.save_attachment_types) >= 1:
        try:
            storage.connect()
            app.include_router(get_storage_router(app))
        except Exception as e:
            logger.error(f"Error during storage connection: {e}", exc_info=True)

    yield

    # Shutdown
    await database.close()


app = FastAPI(title="Teledash API", version="0.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    """API root endpoint."""
    return {"message": "Welcome"}


@app.middleware("http")
async def add_process_time_header(request: Request, call_next) -> Response:
    """Add X-Process-Time header to all responses."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", reload=True, port=8000)
