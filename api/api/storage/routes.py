from collections.abc import Generator

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from api.accounts.auth import get_current_active_verified_user
from api.accounts.models import AccountRead
from api.storage import get_storage
from common.storage import Storage


def file_streamer(response_body) -> Generator[bytes, None, None]:
    """Stream file content from boto3 response."""
    try:
        while True:
            chunk = response_body.read(32 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        response_body.close()


def get_storage_router(app) -> APIRouter:
    """Create and configure the storage API router."""
    router = APIRouter()
    current_active_verified_user = get_current_active_verified_user()

    @router.get(
        "/storage/{bucket_name}/{object_name}",
        response_description="Get a file from storage",
        tags=["storage"],
        responses={
            404: {"description": "The bucket or file was not found."},
            400: {
                "description": "Any other error why the file could not be fetched.",
            },
            200: {
                "description": "Requested file from storage. Can be of any media type.",
                "content": {
                    "*/*": {},
                },
            },
        },
        response_class=StreamingResponse,
    )
    async def get_file(
        bucket_name: str,
        object_name: str,
        attachment: bool = False,
        account: AccountRead = Depends(current_active_verified_user),
        storage: Storage = Depends(get_storage),
    ) -> StreamingResponse:
        """Retrieve and stream a file from object storage (S3/MinIO)."""
        try:
            response = storage.get_object(bucket_name, object_name)
            content_type = response.get("ContentType", "application/octet-stream")
            response_body = response["Body"]
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            status_code = status.HTTP_400_BAD_REQUEST
            if error_code in ["NoSuchBucket", "NoSuchKey", "404"]:
                status_code = status.HTTP_404_NOT_FOUND

            raise HTTPException(status_code, detail=e.response["Error"]["Message"])
        except (BotoCoreError, Exception) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

        return StreamingResponse(
            file_streamer(response_body),
            media_type=content_type,
            headers={
                "Content-Disposition": f"{'attachment; ' if attachment else ''}filename={object_name}"  # noqa: E501
            },
        )

    return router
