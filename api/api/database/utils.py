"""
Database utility helpers.
"""

import logging

logger = logging.getLogger(__name__)


async def collect_storage_refs(
    es_client, index: str, query: dict
) -> set[tuple[str, str]]:
    """
    Collect storage references from messages matching the given query.

    Uses the scroll API to page through all matching messages and extract
    (bucket, object) tuples from attachment.storage_refs. Call this before
    deleting any messages so the refs are still available.

    Args:
        es_client: AsyncElasticsearch client
        index: Index (or index pattern) to search
        query: Elasticsearch query dict

    Returns:
        Set of (bucket, object_name) tuples found in matching messages
    """
    storage_refs: set[tuple[str, str]] = set()
    scroll_id = None

    try:
        response = await es_client.search(
            index=index,
            body={"query": query, "_source": ["attachment.storage_refs"], "size": 1000},
            scroll="1m",
        )
        scroll_id = response.get("_scroll_id")

        while True:
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                break
            for hit in hits:
                for ref in (
                    hit.get("_source", {}).get("attachment", {}).get("storage_refs", [])
                ):
                    if "bucket" in ref and "object" in ref:
                        storage_refs.add((ref["bucket"], ref["object"]))
            try:
                response = await es_client.scroll(scroll_id=scroll_id, scroll="1m")
            except Exception as e:
                logger.error(f"Scroll error on index {index}: {e}", exc_info=True)
                break
    except Exception as e:
        logger.error(
            f"Error collecting storage refs from {index}: {e}", exc_info=True
        )
    finally:
        if scroll_id:
            try:
                await es_client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass

    logger.info(f"Collected {len(storage_refs)} storage references from {index}")
    return storage_refs