from enum import Enum
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from elasticsearch.dsl import Q

from common.settings import settings


class StorageBucketNames(str, Enum):
    thumbnails = "thumbnails"  # One size of a photo or a file/sticker thumbnail.
    photos = "photos"  # photo files
    audios = "audios"  # audio files to be treated as music by the Telegram clients.
    documents = "documents"  # generic file, can be mp3, pdf etc.)
    animations = "animations"  # GIF or H.264/MPEG-4 AVC video without sound
    videos = "videos"  # video files
    voices = "voices"  # voice note (audio)
    video_notes = "video-notes"  # video note files (video)
    stickers = "stickers"  # sticker files (images)


class Storage:
    def __init__(self, connect=True) -> None:
        if connect is True:
            self.connect()

    def connect(self):
        # Determine endpoint URL based on provider
        endpoint_url = self._get_endpoint_url()

        # Configure boto3 client based on provider
        client_config = {
            "aws_access_key_id": settings.storage_access_key,
            "aws_secret_access_key": settings.storage_secret_key,
            "use_ssl": settings.storage_use_ssl,
        }

        if endpoint_url:
            client_config["endpoint_url"] = endpoint_url

        if settings.storage_region:
            client_config["region_name"] = settings.storage_region

        # For S3-compatible providers, use path-style addressing
        if settings.storage_provider == "s3-compatible":
            client_config["config"] = Config(s3={"addressing_style": "path"})

        self.client = boto3.client("s3", **client_config)

        # Create buckets if they don't exist and we have permissions
        buckets = [member.value for member in StorageBucketNames._member_map_.values()]

        for bucket in buckets:
            try:
                if not self.bucket_exists(bucket):
                    self.make_bucket(bucket)
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                # Skip bucket operations if we don't have permissions
                # This allows the storage to work with pre-created buckets
                if error_code in ["403", "Forbidden", "AccessDenied"]:
                    print(
                        f"Warning: No permission to check/create bucket '{bucket}'. Assuming bucket exists."
                    )
                    continue
                else:
                    raise e

    def _get_endpoint_url(self) -> Optional[str]:
        """Get the appropriate endpoint URL based on provider configuration."""
        # AWS with custom endpoint (like Hetzner) or s3-compatible providers
        if settings.storage_provider == "s3-compatible" or (
            settings.storage_provider == "aws"
            and settings.storage_endpoint not in ["localhost:9000", "minio:9000"]
        ):
            endpoint = settings.storage_endpoint
            if not endpoint.startswith(("http://", "https://")):
                protocol = "https" if settings.storage_use_ssl else "http"
                endpoint = f"{protocol}://{endpoint}"
            return endpoint

        # Standard AWS S3 (no custom endpoint)
        return None

    def bucket_exists(self, bucket_name: str) -> bool:
        """Check if bucket exists."""
        try:
            self.client.head_bucket(Bucket=self._get_bucket_name(bucket_name))
            return True
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ["404", "NoSuchBucket"]:
                return False
            else:
                raise e

    def make_bucket(self, bucket_name: str) -> None:
        """Create a bucket."""
        full_bucket_name = self._get_bucket_name(bucket_name)
        try:
            create_bucket_config = {}

            # AWS S3 requires CreateBucketConfiguration for non-us-east-1 regions
            if (
                settings.storage_provider == "aws"
                and settings.storage_region != "us-east-1"
            ):
                create_bucket_config["CreateBucketConfiguration"] = {
                    "LocationConstraint": settings.storage_region
                }

            if create_bucket_config:
                self.client.create_bucket(
                    Bucket=full_bucket_name, **create_bucket_config
                )
            else:
                self.client.create_bucket(Bucket=full_bucket_name)
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code != "BucketAlreadyOwnedByYou":
                raise e

    def _get_bucket_name(self, bucket_name: str) -> str:
        """Get the full bucket name with optional prefix."""
        if settings.storage_bucket_prefix:
            return f"{settings.storage_bucket_prefix}{bucket_name}"
        return bucket_name

    def fput_object(
        self,
        bucket_name: str,
        object_name: str,
        file_path: str,
        content_type: Optional[str] = None,
    ) -> None:
        """Upload a file to the bucket."""
        full_bucket_name = self._get_bucket_name(bucket_name)
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        self.client.upload_file(
            file_path, full_bucket_name, object_name, ExtraArgs=extra_args
        )

    def get_object(self, bucket_name: str, object_name: str):
        """Get an object from the bucket."""
        full_bucket_name = self._get_bucket_name(bucket_name)
        return self.client.get_object(Bucket=full_bucket_name, Key=object_name)

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        """Remove an object from the bucket."""
        full_bucket_name = self._get_bucket_name(bucket_name)
        self.client.delete_object(Bucket=full_bucket_name, Key=object_name)

    def list_objects(self, bucket_name: str, prefix: str = "") -> list:
        """List objects in a bucket with optional prefix."""
        full_bucket_name = self._get_bucket_name(bucket_name)
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            page_iterator = paginator.paginate(Bucket=full_bucket_name, Prefix=prefix)

            objects = []
            for page in page_iterator:
                if "Contents" in page:
                    objects.extend([obj["Key"] for obj in page["Contents"]])
            return objects
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ["404", "NoSuchBucket"]:
                return []
            else:
                raise e

    async def cleanup_orphaned_objects(
        self, database, storage_refs: set[tuple[str, str]]
    ) -> tuple[int, Optional[str]]:
        """
        Check storage objects and delete those not referenced by any messages.

        Args:
            database: Database instance with messages collection access
            storage_refs: Set of (bucket, object_name) tuples to check

        Returns:
            Tuple of (deleted_count, error_summary)
        """

        deleted_count = 0
        errors = []

        for bucket, object_name in storage_refs:
            try:
                # Search for any remaining messages that reference this storage object
                ref_filter = Q(
                    "bool",
                    must=[
                        Q("term", **{"attachment.storage_refs.bucket": bucket}),
                        Q("term", **{"attachment.storage_refs.object": object_name}),
                    ],
                )

                ref_count = await database.messages.count(filter=ref_filter)

                # If no messages reference this storage object, delete it
                # NOTE: There's a potential race condition between the count check and deletion.
                # This is acceptable because chat deletion should be performed when
                # scraping is stopped and no new messages are being added.
                # See DELETE /chats endpoint documentation for warnings.
                if ref_count == 0:
                    self.remove_object(bucket, object_name)
                    deleted_count += 1

            except Exception as storage_error:
                error_msg = f"Error checking/deleting storage object {bucket}/{object_name}: {storage_error}"
                errors.append(error_msg)

        error_summary = "; ".join(errors) if errors else None
        return deleted_count, error_summary


if __name__ == "__main__":
    storage = Storage()
