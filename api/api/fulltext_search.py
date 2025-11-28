from typing import Dict, List, Optional, TypedDict

import regex as re
from elasticsearch.dsl import Q
from elasticsearch.dsl.query import Query as ESQuery


class HighlightFieldConfig(TypedDict):
    """Configuration for a single highlighted field."""

    pre_tags: List[str]
    post_tags: str
    number_of_fragments: int


class HighlightConfig(TypedDict):
    """Elasticsearch highlight configuration."""

    fields: Dict[str, HighlightFieldConfig]


def create_exact_match_query(fields: List[str], search_query: str) -> ESQuery:
    """
    Create exact match query for message search with phrase and token support.

    Parses the search query to extract quoted phrases and individual tokens,
    then constructs an Elasticsearch bool query with must/must_not clauses.
    Tokens prefixed with "-" are excluded from results.

    Args:
        fields: List of Elasticsearch field names to search in (e.g., ["text", "caption"])
        search_query: Search string with optional quoted phrases and -excluded terms

    Returns:
        Elasticsearch bool query with multi_match clauses for phrases and tokens

    Example:
        Input: 'important "exact phrase" -exclude'
        Creates: must=[phrase("exact phrase"), match("important")], must_not=[match("exclude")]

    Note: Phrase exclusion (e.g., -"phrase to exclude") is not yet supported
    """
    phrases = re.findall(r'"([^"]+)"', search_query)

    # Remove phrases from search_query
    query_wo_phrases = re.sub(r'"[^"]+"', "", search_query)

    # Split the remaining query into tokens
    tokens = query_wo_phrases.split()

    must_terms = []
    must_not_terms = []

    for token in tokens:
        if token.startswith("-"):
            must_not_terms.append(token[1:])
        elif token:
            must_terms.append(token)

    must_clauses = []

    # Add phrase queries to must
    for phrase in phrases:
        must_clauses.append(
            Q("multi_match", query=phrase, type="phrase", fields=fields)
        )

    # Add individual word queries to must
    if must_terms:
        must_clauses.append(Q("multi_match", query=" ".join(must_terms), fields=fields))

    # Add must_not clause
    must_not_clauses = []
    if must_not_terms:
        must_not_clauses.append(
            Q("multi_match", query=" ".join(must_not_terms), fields=fields)
        )

    # Combine everything into a bool query
    return Q("bool", must=must_clauses, must_not=must_not_clauses)


def create_flexible_search_query(
    fields: List[str],
    search_query: str,
    fuzzy: Optional[bool] = True,
) -> ESQuery:
    """
    Creates a full-text search query to be used in Elasticsearch search.
    Includes exact matches and fuzzy search.

    Args:
        fields (list): A list of field names to be searched in.
        search_query (str): The search query string.
        fuzzy (bool): If True, applies fuzzy matching, if False, only exact matches.

    Returns:
        elasticsearch.dsl.query.Query: An Elasticsearch query object.
    """
    if fuzzy:
        return Q(
            "bool",
            should=[
                Q("multi_match", query=search_query, fields=fields),  # Exact match
                Q(
                    "multi_match", query=search_query, fields=fields, fuzziness="AUTO"
                ),  # Fuzzy match
            ],
            minimum_should_match=1,  # At least one condition must match
        )
    else:
        return Q(
            "bool",
            should=[
                Q("multi_match", query=search_query, fields=fields)
            ],  # Only exact match
            minimum_should_match=1,
        )


def create_highlight_config(
    fields: List[str],
    pre_tags: List[str] = ["<span class='highlight'>"],
    post_tags: str = "</span>",
) -> HighlightConfig:
    """
    Configures Elasticsearch highlight settings to emphasize matching text in search results for specified fields.

    Args:
        fields (list): A list of field names to be searched in.
        pre_tags (list, optional): A list of HTML tags to be added before the highlighted text.
        post_tags (str, optional): An HTML tag to be added after the highlighted text.

    Returns:
        HighlightConfig: A dictionary containing the highlight configuration.
    """

    base_config: HighlightFieldConfig = {
        "pre_tags": pre_tags,
        "post_tags": post_tags,
        "number_of_fragments": 0,  # Return whole field content
    }
    highlight_config: HighlightConfig = {"fields": {}}
    for field in fields:
        highlight_config["fields"][field] = base_config.copy()

    return highlight_config
