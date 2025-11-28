import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from dateutil.parser import parse as parse_date
from elasticsearch.dsl import AsyncSearch, Q

from api.database.database import Database
from common.database.models.aggregations import AggregatedMetrics
from common.database.models.chat import ClassificationAggregation

logger = logging.getLogger(__name__)


async def determine_appropriate_interval(database: Database, match: Dict) -> timedelta:
    """
    Determines the appropriate interval for aggregating metrics based on the
    total duration of the data in the `metrics` index.

    Args:
        database: An instance of the database connection, which includes an
                  Elasticsearch client.
        match: A dictionary containing the term filter to apply to the search
               query.

    Returns:
        A timedelta object representing the appropriate interval for
        aggregating metrics ("hours" or "days").
    """
    # Get the min and max timestamp
    s = AsyncSearch(using=database.es_client, index="metrics")
    must_queries = []
    for key, value in match.items():
        if key == "ts" and isinstance(value, dict):  # Check for range query
            must_queries.append(Q("range", **{key: value}))
        else:  # Exact match for other fields
            must_queries.append(Q("term", **{key: value}))
    bool_query = Q("bool", must=must_queries)
    s = s.filter(bool_query)

    s.aggs.metric("min_ts", "min", field="ts")

    response = await s.execute()
    # Check if the aggregations contain the expected values
    if not hasattr(response.aggregations.min_ts, "value_as_string") or not hasattr(
        response.aggregations.max_ts, "value_as_string"
    ):
        return timedelta(hours=1)

    min_ts = parse_date(response.aggregations.min_ts.value_as_string)
    max_ts = parse_date(response.aggregations.max_ts.value_as_string)

    # Calculate the total duration in days
    duration = max_ts - min_ts
    total_days = duration.days

    # Determine interval based on length
    if total_days <= 365 * 5:
        return timedelta(hours=1)
    else:
        return timedelta(days=1)


async def aggregate_metrics(
    database: Database,
    match: Dict,
    accumulator: str,
    extended_bounds: Optional[Dict] = None,
) -> Optional[AggregatedMetrics]:
    """
    Aggregate metrics data over time with automatic interval determination.

    Determines the optimal time interval (hourly or daily) based on the data range,
    queries metrics from Elasticsearch with date histogram aggregation, and transforms
    the results into a consistent time series with filled gaps.

    Args:
        database: Database instance with Elasticsearch client
        match: Filter criteria (e.g., {"metadata__user_id": 123, "metadata__type": "message_posted"})
        accumulator: Aggregation type - "sum" (total), "avg" (average), or other ES aggregations
        extended_bounds: Optional min/max timestamps to extend the aggregation range

    Returns:
        AggregatedMetrics with time series data, sum/diff values, and metadata, or None if no data
    """
    # Determine appropriate interval based on data length
    try:
        time_delta = await determine_appropriate_interval(database, match)
    except Exception as e:
        time_delta = timedelta(hours=1)
        logger.warning(f"Error determining appropriate interval: {e}", exc_info=True)

    search = generate_metrics_aggregation_query(
        database, match, accumulator, time_delta, extended_bounds
    )

    # Execute the search with aggregation
    response = await search.execute()

    # Process and transform the results
    metrics_aggregated = await transform_aggregated_metrics(
        response, accumulator, time_delta
    )

    return metrics_aggregated


def generate_metrics_aggregation_query(
    database: Database,
    match: Dict,
    accumulator: str,
    time_delta: timedelta,
    extended_bounds: Optional[Dict] = None,
) -> AsyncSearch:
    """
    Generate Elasticsearch date histogram aggregation query for metrics.

    Constructs a query that buckets metrics by time intervals (hour or day) and applies
    the specified accumulator function (sum, avg, etc.) within each bucket. Handles both
    exact term matches and range queries in the filter criteria.

    Args:
        database: Database instance with Elasticsearch client
        match: Filter dict with term matches (exact) or range queries ({"field": {"gte": value}})
        accumulator: ES aggregation function name ("sum", "avg", "min", "max", etc.)
        time_delta: Bucket interval (timedelta(hours=1) or timedelta(days=1))
        extended_bounds: Optional bounds to extend histogram range beyond actual data

    Returns:
        Configured AsyncSearch object ready for execution
    """
    s = AsyncSearch(using=database.es_client, index="metrics")

    must_queries = []
    range_queries = []

    for key, value in match.items():
        if isinstance(value, dict) and any(
            op in value for op in ["gte", "lte", "gt", "lt"]
        ):
            # If value contains range conditions, create a range query
            range_queries.append(Q("range", **{key: value}))
        else:
            # Otherwise, create a term query
            must_queries.append(Q("term", **{key: value}))

    # Combine the term queries and range queries
    bool_query = Q("bool", must=must_queries)
    if range_queries:
        bool_query = bool_query & Q("bool", filter=range_queries)
    s = s.filter(bool_query)

    # Determine the interval based on time_delta
    if time_delta == timedelta(hours=1):
        interval = "hour"
    else:
        interval = "day"  # default to days

    # Add the aggregation to the search object
    s.aggs.bucket(
        "date_histogram_agg",
        "date_histogram",
        field="ts",
        calendar_interval=interval,
        min_doc_count=0,
        extended_bounds=extended_bounds if extended_bounds else {},
    ).metric("value_agg", accumulator, field="value")

    return s


async def transform_aggregated_metrics(
    response, accumulator: str, time_delta: timedelta
) -> Optional[AggregatedMetrics]:
    """
    Transform Elasticsearch aggregation response into metrics format with filled gaps.

    Takes raw ES date histogram buckets and creates a continuous time series by:
    1. Extracting values from buckets
    2. Filling gaps with 0 (for sum) or None (for avg) where no data exists
    3. Ensuring hourly data has exactly 24 points (last 24 hours)
    4. Computing sum (for "sum" accumulator) or diff (start to end, for "avg")

    Args:
        response: Elasticsearch response with date_histogram_agg buckets
        accumulator: The accumulator type ("sum" or "avg") to determine fill values and calculations
        time_delta: Time interval between buckets (hour or day)

    Returns:
        AggregatedMetrics with filled time series data and computed statistics, or None if empty
    """
    metrics_aggregated = AggregatedMetrics()
    data = []
    sum_value = 0

    buckets = response.aggregations.date_histogram_agg.buckets
    if not buckets:
        return None

    start_date = datetime.fromtimestamp(buckets[0].key / 1000)
    end_date = datetime.fromtimestamp(buckets[-1].key / 1000)

    current_date = start_date
    bucket_index = 0

    while current_date <= end_date:
        if bucket_index < len(buckets):
            bucket = buckets[bucket_index]
            bucket_date = datetime.fromtimestamp(bucket.key / 1000)

            if current_date == bucket_date:
                value = bucket.value_agg.value
                sum_value += value if value is not None else 0
                bucket_index += 1
            else:
                value = 0 if accumulator == "sum" else None
        else:
            value = 0 if accumulator == "sum" else None

        data.append({"date": current_date, "value": value})
        current_date += time_delta

    if time_delta == timedelta(hours=1):
        while len(data) < 24:
            data.append(
                {"date": current_date, "value": 0 if accumulator == "sum" else None}
            )
            current_date += time_delta

    if accumulator == "sum":
        metrics_aggregated.sum = int(sum_value)

    if accumulator == "avg":
        start_value = next(
            (item["value"] for item in data if item["value"] is not None), 0
        )
        end_value = next(
            (item["value"] for item in reversed(data) if item["value"] is not None), 0
        )
        metrics_aggregated.diff = int(end_value - start_value)

    metrics_aggregated.start_date = start_date
    metrics_aggregated.end_date = end_date
    metrics_aggregated.time_delta = int(time_delta.total_seconds())
    metrics_aggregated.data = [item["value"] for item in data]

    return metrics_aggregated


async def aggregate_classification_results(
    chat_id: Optional[int], database: Database
) -> Optional[ClassificationAggregation]:
    """
    Aggregate message classification statistics for a chat or globally.

    Computes counts of successfully classified messages, classification errors,
    and the average classification score (score_pos field) for messages that
    were successfully classified. Used for content moderation insights.

    Args:
        chat_id: Optional chat ID to filter results, or None for global statistics
        database: Database instance for querying messages

    Returns:
        ClassificationAggregation with counts and average score, or None if no classified messages
    """
    try:
        filter_clause = Q("term", **{"chat.id": chat_id}) if chat_id else Q()

        classified_success_count = await database.messages.count(
            filter=filter_clause & Q("term", **{"classification.classified": True})
        )
        if classified_success_count > 0:
            classified_error_count = await database.messages.count(
                filter=filter_clause & Q("term", **{"classification.classified": False})
            )
            s = AsyncSearch(using=database.es_client, index="messages")
            s = s.filter(
                filter_clause & Q("term", **{"classification.classified": True})
            )
            s.aggs.metric("avg_score_pos", "avg", field="classification.score_pos")
            response = await s.execute()
            score_pos_avg = (
                round(response.aggregations.avg_score_pos.value, 3)
                if response.aggregations.avg_score_pos.value
                else None
            )

            return ClassificationAggregation(
                classified_success_count=classified_success_count,
                classified_error_count=classified_error_count,
                score_pos_avg=score_pos_avg,
            )
        else:
            return None

    except Exception as e:
        logger.error(
            f"Error while aggregating classification results for chat {chat_id}: {e}",
            exc_info=True,
        )
        return None
