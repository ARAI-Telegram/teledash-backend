from typing import Any, Dict, List, Optional, Union

from elasticsearch import Elasticsearch
from worker.database.language_analyzer import LanguageAnalyzer


def create_dynamic_templates() -> List[Dict[str, Any]]:
    """
    Creates a dynamic template for mapping newly added string fields as keywords in Elasticsearch.
    """
    return [
        {
            "strings_as_keywords": {
                "match_mapping_type": "string",
                "mapping": {"type": "keyword", "ignore_above": 256},
            }
        }
    ]


def map_lang_code_to_analyzer() -> Dict[str, str]:
    """
    Maps language codes to their corresponding text analyzers using the LanguageAnalyzer configuration.
    """
    lang_code_to_analyzer = {}
    for lang in LanguageAnalyzer:
        for code in lang.lang_codes:
            lang_code_to_analyzer[code] = lang.analyzer
    return lang_code_to_analyzer


def add_lang_analyzers_to_text_fields(
    properties: Dict[str, Any], language: Optional[str]
) -> None:
    """
    Adds text analyzers to specified text fields within given properties based on the provided language.

    Parameters:
        properties (dict): A dictionary representing JSON properties where analyzers
                           need to be applied to specific text fields.
        language (str): The language code for which the analyzer should be applied.
                        If the language code is not found, the 'standard' analyzer is used.
    """
    analyzer_map = map_lang_code_to_analyzer()
    # Use "standard" if language is None or not in analyzer_map
    lang_analyzer = analyzer_map.get(language or "standard", "standard")

    fields = [
        "text",
        "caption",
        "attachment.transcription",
    ]
    for field in fields:
        # Handle nested fields like 'attachment.transcription'
        field_parts = field.split(".")
        current_properties = properties

        # Traverse to the correct property based on the field path, creating missing levels
        for part in field_parts[:-1]:
            current_properties = current_properties.get(part, {}).get("properties", {})

        # Apply the analyzer to the field
        if field_parts[-1] in current_properties:
            current_properties[field_parts[-1]]["analyzer"] = lang_analyzer


def create_index_for_chatmessages(
    es: Elasticsearch, chat_id: Union[str, int], language: Optional[str]
) -> None:
    """
    Dynamically creates an Elasticsearch index for chat messages with the appropriate analyzers.

    Parameters:
        es (Elasticsearch): Elasticsearch client instance.
        chat_id (Union[str, int]): The ID of the chat for which the index is being created.
        language (Optional[str]): The language code for the chat messages.
    """
    index_name = f"messages_{chat_id}"

    # Define the minimal analyzer in the settings
    settings = {
        "analysis": {
            "analyzer": {
                "minimal": {
                    "type": "custom",
                    "tokenizer": "whitespace",
                    "filter": ["lowercase"],
                }
            },
            "char_filter": {"html_strip": {"type": "html_strip"}},
        }
    }

    # Define the mappings with multi-fields for both language-specific and minimal analyzers
    mappings = {
        "properties": {
            "text": {
                "type": "text",
                "fields": {
                    "minimal": {
                        "type": "text",
                        "analyzer": "minimal",  # Subfield uses the minimal analyzer
                    }
                },
            },
            "caption": {
                "type": "text",
                "fields": {"minimal": {"type": "text", "analyzer": "minimal"}},
            },
            "attachment": {
                "properties": {
                    "transcription": {
                        "type": "text",
                        "fields": {"minimal": {"type": "text", "analyzer": "minimal"}},
                    },
                },
            },
            "date": {"type": "date"},
            "classification": {
                "properties": {
                    "classified": {"type": "boolean"},
                    "error": {"type": "keyword", "ignore_above": 256},
                    "processed_at": {"type": "date"},
                    "score_pos": {"type": "float"},
                }
            },
        },
        "dynamic_templates": create_dynamic_templates(),
    }

    add_lang_analyzers_to_text_fields(mappings["properties"], language)

    # Create the index with the settings and mappings
    if not es.indices.exists(index=index_name):
        es.indices.create(
            index=index_name,
            body={
                "settings": settings,
                "mappings": mappings,
                "aliases": {"messages": {}},
            },
        )
        print(f"Created index: {index_name}")
    else:
        print(f"Index {index_name} already exists")
