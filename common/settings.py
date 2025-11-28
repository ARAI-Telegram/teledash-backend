from typing import List, Literal, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings

# We maintain a list of allowed attachment types that we are able to process, since Telegram adds new types of attachments from time to time that might result in unexpected behavior.
allowed_attachment_types = [
    "AUDIO",
    "DOCUMENT",
    "PHOTO",
    "STICKER",
    "VIDEO",
    "ANIMATION",
    "VOICE",
    "VIDEO_NOTE",
    "CONTACT",
    "LOCATION",
    "VENUE",
    "POLL",
    "WEB_PAGE",
    "DICE",
    "GAME",
]


class Settings(BaseSettings):
    # === REQUIRED SETTINGS (no defaults) ===
    # Storage credentials
    storage_access_key: str
    storage_secret_key: str

    # Authentication
    jwt_secret: str

    # === OPTIONAL SETTINGS (have defaults) ===
    # Monitoring - Flower (optional, only needed if using Celery monitoring)
    flower_user: Optional[str] = None
    flower_password: Optional[str] = None

    # Project
    compose_project_name: str = "teledash"

    # Telegram API
    telegram_test_mode: bool = False

    # Elasticsearch
    es_host: str = "elastic"
    es_port: int = 9200
    es_scheme: Literal["http", "https"] = "http"

    # Storage Provider
    storage_provider: Literal["aws", "s3-compatible"] = "s3-compatible"
    storage_region: Optional[str] = None
    storage_use_ssl: bool = False
    storage_endpoint: str = "minio:9000"  # Custom endpoint for non-AWS providers
    storage_bucket_prefix: str = ""  # Optional prefix for bucket names

    # Flower (Celery monitoring)
    flower_host: str = "flower"
    flower_port: int = 5555

    # Scraping
    scrape_chats_max_days: int = 7
    scrape_chats_interval_minutes: int = 30
    scrape_users: bool = False

    # Attachments
    save_attachments: bool = True
    save_attachment_types: List[str] = [
        "animation",
        "audio",
        "document",
        "photo",
        "sticker",
        "video",
        "video_note",
        "voice",
        "web_page",
    ]  # See allowed_attachment_types list for allowed types
    keep_attachment_files_days: int = 0

    # Live Scraping
    live_updates: bool = False
    live_concurrency: int = 1  # Number of concurrent live scraping tasks per client. Must be at least equal to the number of active Telegram clients that scrape live!
    live_deletions: Literal["ignore", "mark", "delete"] = "mark"

    # Authentication
    jwt_lifetime_seconds: int = 3600

    # Language Detection (for language specific analyzers in Elasticsearch)
    fallback_language: str = "en"

    # API
    api_allow_origins: List[str] = ["http://localhost:3000"]

    # Semantic Search
    semantic_text_search_api: str = "http://text-search-api:8001/search"
    semantic_image_search_api: str = "http://image-search-api:8002/search"

    @model_validator(mode="before")
    def check_attachment_types_if_enabled(cls, values) -> dict:
        save_attachments = values.get("save_attachments")
        attachment_types = values.get("save_attachment_types", [])
        if save_attachments and attachment_types:
            invalid_types = [
                t for t in attachment_types if t.upper() not in allowed_attachment_types
            ]
            if invalid_types:
                raise ValueError(
                    f'"SAVE_ATTACHMENT_TYPES" contains invalid type(s): {", ".join(invalid_types)}'
                )
        return values

    @model_validator(mode="before")
    def validate_storage_configuration(cls, values) -> dict:
        """Validate storage provider configuration."""
        storage_provider = values.get("storage_provider", "s3-compatible")
        storage_region = values.get("storage_region")

        # AWS S3 requires region
        if storage_provider == "aws" and not storage_region:
            raise ValueError("storage_region is required when using AWS provider")

        return values

    @model_validator(mode="before")
    def validate_flower_configuration(cls, values) -> dict:
        """Validate that if one Flower credential is set, both must be set."""
        flower_user = values.get("flower_user")
        flower_password = values.get("flower_password")

        # If one is set, both must be set
        if (flower_user is not None and flower_password is None) or (
            flower_password is not None and flower_user is None
        ):
            raise ValueError(
                "Both FLOWER_USER and FLOWER_PASSWORD must be set together, or neither should be set"
            )

        return values


settings = Settings()  # type: ignore
