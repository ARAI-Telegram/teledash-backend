import os

from elasticsearch import Elasticsearch


def create_dynamic_templates() -> None:
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


def create_url_hashtag_pipeline():
    """
    Creates a pipeline for extracting URLs and hashtags from the 'text' or 'caption' fields,
    using information from 'entities' or 'caption_entities'. Counts text length if caption or text available.

    This pipeline performs the following tasks:
    1. Extracts URLs and hashtags from the 'text' or 'caption' fields by using the offset and length provided in the 'entities'
       or 'caption_entities' fields. These fields indicate where in the text the URLs and hashtags are located.
    2. Checks if existent URLs already contain a scheme (like 'http://') and adds 'http://' if not, for the parser to work correctly.
    3. Stores extracted entities in separate fields ('extracted_urls' and 'extracted_hashtags', both of type List)
    4. Parses the URLs using the 'uri_parts' processor.
    5. Counts the character length of 'text' or 'caption' and stores it in a new field 'text_length' if applicable.

    Returns:
        dict: A dictionary representing the pipeline configuration.
    """
    return {
        "description": "Extract URLs and hashtags, parse the URLs, count text length",
        "processors": [
            {
                "script": {
                    "source": """
                    // Function to extract URLs
                    def extractUrls(def entities, def text) {
                        def urls = [];
                        if (entities != null) {
                            for (def entity : entities) {
                                if (entity.type == 'url') {
                                    def offset = entity.offset;
                                    def length = entity.length;
                                    if (text != null && offset + length <= text.length()) {
                                        def url = text.substring(offset, offset + length);

                                         // Check if URL already contains a scheme by looking for "://" pattern
                                        if (url.indexOf("://") == -1) {
                                            // if URL doesn't have a scheme, add http://
                                            url = "http://" + url;
                                        }
                                        
                                        urls.add(url);
                                    }
                                }
                            }
                        }
                        return urls;
                    }

                    // Function to extract hashtags
                    def extractHashtags(def entities, def text) {
                        def hashtags = [];
                        if (entities != null) {
                            for (def entity : entities) {
                                if (entity.type == 'hashtag') {
                                    def offset = entity.offset;
                                    def length = entity.length;
                                    if (text != null && offset + length <= text.length()) {
                                        def hashtag = text.substring(offset, offset + length).toLowerCase();
                                        hashtags.add(hashtag);
                                    }
                                }
                            }
                        }
                        return hashtags;
                    }

                    // Initialize extracted fields
                    ctx.extracted_urls = [];
                    ctx.extracted_hashtags = [];

                    // Define text fields and entity fields
                    def textField = ctx.containsKey('text') ? 'text' : (ctx.containsKey('caption') ? 'caption' : null);
                    def textSource = textField != null ? ctx[textField] : null;

                    // Process entities from both 'entities' and 'caption_entities'
                    if (textSource != null) {
                        def allEntities = [];
                        if (ctx.containsKey('entities')) {
                            allEntities.addAll(ctx.entities);
                        }
                        if (ctx.containsKey('caption_entities')) {
                            allEntities.addAll(ctx.caption_entities);
                        }

                        ctx.extracted_urls = extractUrls(allEntities, textSource);
                        ctx.extracted_hashtags = extractHashtags(allEntities, textSource);

                        // Count the character length of the text or caption
                        ctx.text_length = textSource.length();
                    }
                    """
                }
            },
            {
                "foreach": {
                    "field": "extracted_urls",
                    "processor": {
                        "uri_parts": {
                            "field": "_ingest._value",
                            "target_field": "_ingest._value",
                            "remove_if_successful": False,
                        }
                    },
                }
            },
        ],
    }


# Create index and define mappings
def create_initial_mappings():
    dynamic_templates = create_dynamic_templates()

    indices = {
        "accounts": {},
        "chats": {
            "mappings": {
                "properties": {
                    "title": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "username": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "description": {"type": "text"},
                    "language": {"type": "keyword"},
                    "is_verified": {"type": "boolean"},
                    "is_restricted": {"type": "boolean"},
                    "is_creator": {"type": "boolean"},
                    "is_scam": {"type": "boolean"},
                    "is_fake": {"type": "boolean"},
                    "is_support": {"type": "boolean"},
                    "updated_at": {"type": "date"},
                    "created_at": {"type": "date"},
                    "scraped_at": {"type": "date"},
                    "members_count": {"type": "integer"},
                }
            }
        },
        "users": {
            "mappings": {
                "properties": {
                    "title": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "username": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "first_name": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "last_name": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "updated_at": {"type": "date"},
                }
            }
        },
        "metrics": {"mappings": {"properties": {"ts": {"type": "date"}}}},
        "clients": {
            "mappings": {
                "properties": {
                    "session_hash": {
                        "type": "keyword"
                    },  # we don't want a limit of 256 bytes here
                    "user_id": {"type": "long"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "is_active": {"type": "boolean"},
                    "chats": {"type": "object"},
                }
            }
        },
    }

    settings = {"analysis": {"char_filter": {"html_strip": {"type": "html_strip"}}}}

    for index in indices.values():
        if "mappings" not in index:
            index["mappings"] = {}
        index["mappings"]["dynamic_templates"] = dynamic_templates

    return indices, settings


def create_default_template(es_client):
    """
    Creates a default index template that sets number_of_replicas to 0 for all indices.
    This ensures single-node clusters stay green instead of yellow.
    """
    template_name = "default-single-node-template"
    template_body = {
        "index_patterns": ["*"],  # Apply to all indices
        "priority": 1,  # Low priority so specific templates can override
        "template": {"settings": {"number_of_replicas": 0}},
    }

    try:
        es_client.indices.put_index_template(name=template_name, body=template_body)
        print(f"Created default index template: {template_name} (0 replicas)")
    except Exception as e:
        print(f"Error creating default index template: {e}")


if __name__ == "__main__":
    es_url = os.getenv("ELASTICSEARCH_URL", "http://elastic:9200")

    # Initialize Elasticsearch client
    es = Elasticsearch([es_url])

    # Create default index template with 0 replicas for single-node clusters
    create_default_template(es)

    # Create the pipeline
    pipeline_id = "url_hashtag_pipeline"
    pipeline_body = create_url_hashtag_pipeline()
    # Check if the pipeline already exists, create or update it
    try:
        es.ingest.put_pipeline(id=pipeline_id, body=pipeline_body)
        print(f"Created or updated pipeline: {pipeline_id}")
    except Exception as e:
        print(f"Error creating or updating pipeline: {e}")

    indices, settings = create_initial_mappings()

    for index_name, index_config in indices.items():
        if not es.indices.exists(index=index_name):
            es.indices.create(
                index=index_name,
                body={
                    "settings": settings,
                    "mappings": index_config["mappings"],
                },
            )
            print(f"Created index: {index_name}")
        else:
            print(f"Index {index_name} already exists")

    print("Elasticsearch initialization script completed.")
