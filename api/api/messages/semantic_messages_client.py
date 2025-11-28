from datetime import datetime
from typing import List, Optional, TypedDict

from fastapi import HTTPException, status
from httpx import AsyncClient, HTTPError

from api.messages.models import MessageSearchType
from common.database.models.message import MessageOut
from common.settings import settings


class SemanticMatch(TypedDict):
    id: int
    score: float


async def get_semantic_messages(
    search_query: str,
    search_type: MessageSearchType,
    chat_ids: Optional[List[int]] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> list[SemanticMatch]:
    """
    Query external semantic search API to get matching message IDs with similarity scores.
    
    Routes the search to either the text embedding or image embedding API based on
    search_type. Sends query parameters including optional chat and date filters.
    The external API returns message IDs ranked by semantic similarity (vector distance).
    
    Args:
        search_query: The search query string (text prompt or image description)
        search_type: SEMANTIC_TEXT (text embedding) or SEMANTIC_IMAGE (image embedding)
        chat_ids: Optional list of chat IDs to restrict search scope
        date_from: Optional start date to filter messages
        date_to: Optional end date to filter messages
    
    Returns:
        List of dicts with 'id' (message ID) and 'score' (similarity score)
    
    Raises:
        HTTPException: 400 if invalid search_type, 502 if semantic service fails
        
    Note:
        Currently uses insecure SSL (verify=False) - should enable certificate
        verification in production environments
    """
    if search_type == MessageSearchType.SEMANTIC_TEXT:
        api_url = settings.semantic_text_search_api
    elif search_type == MessageSearchType.SEMANTIC_IMAGE:
        api_url = settings.semantic_image_search_api
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid search type",
        )

    try:
        # FIXME: Use secure connection with SSL certificates in production if needed
        params = {"query": search_query}
        if chat_ids:
            params["chat_ids"] = ",".join(map(str, chat_ids))

        # Add date filters if provided
        if date_from:
            params["date_from"] = date_from.isoformat()
        if date_to:
            params["date_to"] = date_to.isoformat()
        async with AsyncClient(verify=False) as client:
            response = await client.get(
                api_url,
                params=params,
            )
            response.raise_for_status()
            return response.json()

    except HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Semantic search service error: {str(e)}",
        )


def map_classifier_results_to_messages(
    messages: List[MessageOut], score_map: dict
) -> List[MessageOut]:
    """
    Map semantic search similarity scores to message objects.
    
    Takes messages retrieved from Elasticsearch and enriches them with
    semantic_score values from the semantic search API results. Only
    includes messages that have a corresponding score in the score_map.
    
    Args:
        messages: List of message objects from Elasticsearch
        score_map: Dict mapping message IDs to similarity scores from semantic API
    
    Returns:
        List of messages with semantic_score field populated, filtered to only
        include messages present in score_map
    """
    message_outs: List[MessageOut] = []
    if messages:
        for msg in messages:
            # Access the id from the Message object to find the corresponding score in score_map
            message_id = msg.id
            semantic_score = score_map.get(message_id)

            if semantic_score is not None:
                msg.semantic_score = semantic_score
                message_outs.append(msg)

    return message_outs
