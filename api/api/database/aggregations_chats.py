import logging
from datetime import datetime, timedelta
from typing import Any, List, Literal, Optional

from elasticsearch import BadRequestError
from fastapi import HTTPException, status

from api.database.database import Database
from common.database.models.aggregations import AggregatedMetrics

logger = logging.getLogger(__name__)


async def get_chat_metrics(
    chat_ids: Optional[List[int]],
    total: bool = False,
    yesterday: bool = True,
    total_interval: Optional[Literal["day", "hour"]] = "hour",
) -> dict:
    """
    Fetch aggregated chat metrics for specific chats or globally based on the provided ids.
    If a "too many buckets" error occurs, it retries the query with a larger interval.
    Args:
        - chat_ids (Optional[List[int]]): A list of chat IDs to fetch metrics for. If None, fetches global metrics.
        - total (bool): If True, fetches total metrics across all chats. Defaults to False.
        - yesterday (bool): If True, fetches metrics for yesterday. Defaults to True.
        - total_interval (Optional[Literal["day", "hour"]]): The interval for total metrics aggregation.
            Defaults to "hour". If "too many buckets" error occurs, retries with "day".
    Returns:
        dict: A dictionary containing the transformed response with chat metrics.
    Raises:
        HTTPException: If the Elasticsearch query fails for reasons other than "too many buckets".
    """
    database = Database()
    try:
        query = build_query(
            chat_ids,
            total,
            yesterday,
            total_interval=total_interval,
        )
        response = await database.es_client.search(index="metrics", body=query)

        return await transform_response(
            response, chat_ids, total, yesterday, total_interval
        )
    except BadRequestError as e:
        caused_by = e.info.get("error", {})
        while "caused_by" in caused_by:
            caused_by = caused_by["caused_by"]
        error_type = caused_by.get("type", "").lower()

        if error_type == "too_many_buckets_exception" and total_interval != "day":
            logger.warning(
                "Too many buckets error occurred. Retrying with 'day' interval."
            )
            query = build_query(chat_ids, total, yesterday, total_interval="day")
            response = await database.es_client.search(index="metrics", body=query)
            return await transform_response(response, chat_ids, total, yesterday, "day")

        else:
            logger.error("Elasticsearch query failed", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Elasticsearch query failed: {str(e)}",
            )


def build_query(
    chat_ids: Optional[List[int]],
    total: bool,
    yesterday: bool,
    total_interval: Optional[Literal["day", "hour"]],
) -> dict:
    """
    Build the Elasticsearch query for chat aggregations.
    """
    base_filter = []
    if chat_ids:
        base_filter.append({"terms": {"metadata.chat_id": chat_ids}})
    else:
        base_filter.append({"bool": {"filter": []}})

    aggs = {}
    if total:
        aggs.update(
            {
                "activity_total": {
                    "filter": {"term": {"metadata.type": "message_posted"}},
                    "aggs": {
                        "by_time": {
                            "date_histogram": {
                                "field": "ts",
                                "calendar_interval": total_interval,
                                "min_doc_count": 0,
                            },
                            "aggs": {"sum_value": {"sum": {"field": "value"}}},
                        }
                    },
                },
                "growth_total": {
                    "filter": {"term": {"metadata.type": "chat_members_count"}},
                    "aggs": {
                        "by_time": {
                            "date_histogram": {
                                "field": "ts",
                                "calendar_interval": total_interval,
                                "min_doc_count": 0,
                            },
                            "aggs": {"avg_value": {"avg": {"field": "value"}}},
                        }
                    },
                },
            }
        )

    if yesterday:
        aggs.update(
            {
                "activity_last_day": {
                    "filter": {
                        "bool": {
                            "must": [
                                {"term": {"metadata.type": "message_posted"}},
                                {"range": {"ts": {"gte": "now-24h/h"}}},
                            ]
                        }
                    },
                    "aggs": {
                        "by_time": {
                            "date_histogram": {
                                "field": "ts",
                                "calendar_interval": "hour",
                                "min_doc_count": 0,
                                "extended_bounds": {
                                    "min": "now-24h/h",
                                    "max": "now/h",
                                },
                            },
                            "aggs": {"sum_value": {"sum": {"field": "value"}}},
                        }
                    },
                },
                "growth_last_day": {
                    "filter": {
                        "bool": {
                            "must": [
                                {"term": {"metadata.type": "chat_members_count"}},
                                {"range": {"ts": {"gte": "now-24h/h"}}},
                            ]
                        }
                    },
                    "aggs": {
                        "by_time": {
                            "date_histogram": {
                                "field": "ts",
                                "calendar_interval": "hour",
                                "min_doc_count": 0,
                                "extended_bounds": {
                                    "min": "now-24h/h",
                                    "max": "now/h",
                                },
                            },
                            "aggs": {"avg_value": {"avg": {"field": "value"}}},
                        }
                    },
                },
            }
        )

    query = {
        "query": {"bool": {"filter": base_filter}},
        "size": 0,
        "aggs": {
            "chats": {
                "terms": {"field": "metadata.chat_id", "size": len(chat_ids)},
                "aggs": aggs,
            }
        }
        if chat_ids
        else aggs,
    }

    return query


async def transform_response(
    response: Any,
    chat_ids: Optional[List[int]],
    total: bool,
    yesterday: bool,
    total_interval: Optional[Literal["day", "hour"]] = "day",
) -> dict:
    """
    Transform the Elasticsearch aggregation response into a structured format.
    """
    chat_metrics = {}
    if total_interval == "hour":
        total_timedelta = timedelta(hours=1)
    else:
        total_timedelta = timedelta(days=1)

    if chat_ids:
        for chat_bucket in response["aggregations"]["chats"]["buckets"]:
            chat_id = chat_bucket["key"]
            metrics = {}

            if total:
                # Transform msg_total buckets
                if (
                    "activity_total" in chat_bucket
                    and "by_time" in chat_bucket["activity_total"]
                ):
                    msg_total_buckets = chat_bucket["activity_total"]["by_time"][
                        "buckets"
                    ]
                    metrics["activity_total"] = await transform_metric_buckets(
                        msg_total_buckets,
                        kind="sum",
                        value_field="sum_value",
                        time_delta=total_timedelta,
                    )

                # Transform members_total buckets
                if (
                    "growth_total" in chat_bucket
                    and "by_time" in chat_bucket["growth_total"]
                ):
                    members_total_buckets = chat_bucket["growth_total"]["by_time"][
                        "buckets"
                    ]
                    metrics["growth_total"] = await transform_metric_buckets(
                        members_total_buckets,
                        kind="avg",
                        value_field="avg_value",
                        time_delta=total_timedelta,
                    )

            if yesterday:
                # Transform msg_last_24h buckets
                if (
                    "activity_last_day" in chat_bucket
                    and "by_time" in chat_bucket["activity_last_day"]
                ):
                    msg_last_24h_buckets = chat_bucket["activity_last_day"]["by_time"][
                        "buckets"
                    ]
                    metrics["activity_last_day"] = await transform_metric_buckets(
                        msg_last_24h_buckets,
                        kind="sum",
                        value_field="sum_value",
                        time_delta=timedelta(hours=1),
                    )

                # Transform members_last_24h buckets
                if (
                    "growth_last_day" in chat_bucket
                    and "by_time" in chat_bucket["growth_last_day"]
                ):
                    members_last_24h_buckets = chat_bucket["growth_last_day"][
                        "by_time"
                    ]["buckets"]
                    metrics["growth_last_day"] = await transform_metric_buckets(
                        members_last_24h_buckets,
                        kind="avg",
                        value_field="avg_value",
                        time_delta=timedelta(hours=1),
                    )

            chat_metrics[chat_id] = metrics
    else:
        chat_metrics["global"] = {}
        for metric_key in response["aggregations"]:
            if total and metric_key in ["activity_total", "growth_total"]:
                buckets = response["aggregations"][metric_key]["by_time"]["buckets"]
                chat_metrics["global"][metric_key] = await transform_metric_buckets(
                    buckets,
                    kind="sum" if "activity" in metric_key else "avg",
                    value_field="sum_value"
                    if "activity" in metric_key
                    else "avg_value",
                    time_delta=total_timedelta,
                )
            if yesterday and metric_key in [
                "activity_last_day",
                "growth_last_day",
            ]:
                buckets = response["aggregations"][metric_key]["by_time"]["buckets"]
                chat_metrics["global"][metric_key] = await transform_metric_buckets(
                    buckets,
                    kind="sum" if "activity" in metric_key else "avg",
                    value_field="sum_value"
                    if "activity" in metric_key
                    else "avg_value",
                    time_delta=timedelta(hours=1),
                )

    return chat_metrics


async def transform_metric_buckets(
    buckets, kind: str, value_field: str, time_delta: timedelta
) -> Optional[AggregatedMetrics]:
    """
    Transform metrics to list of integers, assuming date_histogram returns consistent buckets
    with `min_doc_count: 0` and `extended_bounds` applied.

    - kind = "sum" or "avg"
    - value_field = "sum_value" or "avg_value"
    """
    if not buckets:
        return None

    metrics = AggregatedMetrics()
    data = []

    for bucket in buckets:
        value = bucket.get(value_field, {}).get("value")
        if value is not None:
            data.append(int(round(value)))
        else:
            data.append(0 if kind == "sum" else None)

    metrics.data = data
    metrics.start_date = datetime.fromtimestamp(buckets[0]["key"] / 1000)
    metrics.end_date = datetime.fromtimestamp(buckets[-1]["key"] / 1000)
    metrics.time_delta = int(time_delta.total_seconds())

    if kind == "sum":
        metrics.sum = sum(v for v in data if v is not None)
    elif kind == "avg":
        non_null_values = [v for v in data if v is not None]
        if len(non_null_values) >= 2:
            metrics.diff = non_null_values[-1] - non_null_values[0]
        else:
            metrics.diff = 0

    return metrics
