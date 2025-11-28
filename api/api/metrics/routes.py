import logging

from elasticsearch.dsl import Q
from elasticsearch.exceptions import NotFoundError
from fastapi import APIRouter, Depends

from api.accounts.auth import get_current_active_verified_user
from api.accounts.models import AccountRead
from api.database import get_database
from api.database.aggregations import aggregate_classification_results
from api.database.aggregations_chats import get_chat_metrics
from api.database.database import Database
from common.database.models.chat import GlobalMetrics

logger = logging.getLogger(__name__)


def get_metrics_router(app) -> APIRouter:
    """Create and configure the metrics API router."""
    router = APIRouter()

    @router.get(
        "/metrics",
        response_description="List all metrics",
        tags=["metrics"],
        response_model=GlobalMetrics,
        response_model_exclude_none=True,
        response_model_exclude_unset=True,
    )
    async def list_metrics(
        account: AccountRead = Depends(get_current_active_verified_user()),
        database: Database = Depends(get_database),
    ) -> GlobalMetrics:
        """Get global statistics including total counts and aggregated activity metrics."""
        users_count = await database.users.count()
        chats_count = await database.chats.count()
        try:  # messages indices may not exist yet, while chats and users do
            messages_count = await database.messages.count()
            photos_count = await database.messages.count(
                Q("term", attachment__type="photo")
            )  # or equivalently: Q("term", {"attachment.type": "photo"}
            videos_count = await database.messages.count(
                Q("term", attachment__type="video")
            )
            voices_count = await database.messages.count(
                Q("term", attachment__type="voice")
            )
        except NotFoundError:
            # Handle case when messages index doesn't exist
            messages_count = 0
            photos_count = 0
            videos_count = 0
            voices_count = 0
        try:
            global_metrics = await get_chat_metrics(
                chat_ids=None,  # No chat IDs, calculate globally
                total=True,
                yesterday=False,  # Skip yesterday's metrics
                total_interval="hour",
            )
            activity_total = global_metrics.get("global", {}).get(
                "activity_total", None
            )
            growth_total = global_metrics.get("global", {}).get("growth_total", None)

        except Exception as e:
            logger.error(
                f"Unexpected error while fetching global metrics: {str(e)}",
                exc_info=True,
            )
            activity_total = None
            growth_total = None

        classification_total = await aggregate_classification_results(
            chat_id=None, database=database
        )

        metrics = GlobalMetrics(
            users_count=users_count,
            chats_count=chats_count,
            messages_count=messages_count,
            photos_count=photos_count,
            activity_total=activity_total,
            growth_total=growth_total,
            videos_count=videos_count,
            voices_count=voices_count,
            classification_total=classification_total,
        )

        return metrics

    return router
