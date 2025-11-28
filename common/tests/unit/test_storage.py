from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

from common.storage import Storage, StorageBucketNames


class TestStorage:
    """Test cases for the Storage class with boto3 backend."""

    @pytest.fixture
    def mock_settings_aws(self):
        """Mock settings for AWS S3."""
        with patch("common.storage.settings") as mock_settings:
            mock_settings.storage_provider = "aws"
            mock_settings.storage_region = "us-east-1"
            mock_settings.storage_use_ssl = True
            mock_settings.storage_endpoint = (
                "minio:9000"  # Default, should be ignored for AWS
            )
            mock_settings.storage_access_key = "test_access_key"
            mock_settings.storage_secret_key = "test_secret_key"
            mock_settings.storage_bucket_prefix = ""
            yield mock_settings

    @pytest.fixture
    def mock_settings_hetzner(self):
        """Mock settings for Hetzner Object Storage."""
        with patch("common.storage.settings") as mock_settings:
            mock_settings.storage_provider = "aws"
            mock_settings.storage_region = "eu-central-1"
            mock_settings.storage_use_ssl = True
            mock_settings.storage_endpoint = "fsn1.your-objectstorage.com"
            mock_settings.storage_access_key = "hetzner_access_key"
            mock_settings.storage_secret_key = "hetzner_secret_key"
            mock_settings.storage_bucket_prefix = ""
            yield mock_settings

    @pytest.fixture
    def mock_settings_r2(self):
        """Mock settings for Cloudflare R2."""
        with patch("common.storage.settings") as mock_settings:
            mock_settings.storage_provider = "s3-compatible"
            mock_settings.storage_region = None
            mock_settings.storage_use_ssl = True
            mock_settings.storage_endpoint = "account-id.r2.cloudflarestorage.com"
            mock_settings.storage_access_key = "r2_access_key"
            mock_settings.storage_secret_key = "r2_secret_key"
            mock_settings.storage_bucket_prefix = ""
            yield mock_settings

    @pytest.fixture
    def mock_settings_minio(self):
        """Mock settings for MinIO."""
        with patch("common.storage.settings") as mock_settings:
            mock_settings.storage_provider = "s3-compatible"
            mock_settings.storage_region = None
            mock_settings.storage_use_ssl = False
            mock_settings.storage_endpoint = "minio:9000"
            mock_settings.storage_access_key = "minio_user"
            mock_settings.storage_secret_key = "minio_password"
            mock_settings.storage_bucket_prefix = "test-"
            yield mock_settings

    @patch("common.storage.boto3.client")
    def test_aws_s3_configuration(self, mock_boto3_client, mock_settings_aws):
        """Test AWS S3 configuration uses default endpoints."""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client
        mock_client.head_bucket.return_value = True

        storage = Storage(connect=True)

        # Verify boto3 client called with correct AWS configuration
        mock_boto3_client.assert_called_once_with(
            "s3",
            aws_access_key_id="test_access_key",
            aws_secret_access_key="test_secret_key",
            use_ssl=True,
            region_name="us-east-1",
            # No endpoint_url for AWS
        )

    @patch("common.storage.boto3.client")
    def test_hetzner_configuration(self, mock_boto3_client, mock_settings_hetzner):
        """Test Hetzner Object Storage configuration."""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client
        mock_client.head_bucket.return_value = True

        storage = Storage(connect=True)

        # Verify boto3 client called with Hetzner endpoint
        mock_boto3_client.assert_called_once_with(
            "s3",
            aws_access_key_id="hetzner_access_key",
            aws_secret_access_key="hetzner_secret_key",
            use_ssl=True,
            endpoint_url="https://fsn1.your-objectstorage.com",
            region_name="eu-central-1",
        )

    @patch("common.storage.boto3.client")
    @patch("common.storage.Config")
    def test_cloudflare_r2_configuration(
        self, mock_config, mock_boto3_client, mock_settings_r2
    ):
        """Test Cloudflare R2 configuration with path-style addressing."""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client
        mock_client.head_bucket.return_value = True

        mock_config_instance = Mock()
        mock_config.return_value = mock_config_instance

        storage = Storage(connect=True)

        # Verify path-style addressing config is created
        mock_config.assert_called_once_with(s3={"addressing_style": "path"})

        # Verify boto3 client called with R2 configuration
        mock_boto3_client.assert_called_once_with(
            "s3",
            aws_access_key_id="r2_access_key",
            aws_secret_access_key="r2_secret_key",
            use_ssl=True,
            endpoint_url="https://account-id.r2.cloudflarestorage.com",
            config=mock_config_instance,
        )

    @patch("common.storage.boto3.client")
    @patch("common.storage.Config")
    def test_minio_configuration(
        self, mock_config, mock_boto3_client, mock_settings_minio
    ):
        """Test MinIO configuration with path-style addressing."""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client
        mock_client.head_bucket.return_value = True

        mock_config_instance = Mock()
        mock_config.return_value = mock_config_instance

        storage = Storage(connect=True)

        # Verify path-style addressing config is created
        mock_config.assert_called_once_with(s3={"addressing_style": "path"})

        # Verify boto3 client called with MinIO configuration
        mock_boto3_client.assert_called_once_with(
            "s3",
            aws_access_key_id="minio_user",
            aws_secret_access_key="minio_password",
            use_ssl=False,
            endpoint_url="http://minio:9000",
            config=mock_config_instance,
        )

    @patch("common.storage.boto3.client")
    def test_bucket_operations(self, mock_boto3_client, mock_settings_minio):
        """Test bucket operations (exists, create)."""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client

        # Mock bucket doesn't exist, then gets created
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadBucket"
        )
        mock_client.create_bucket.return_value = None

        storage = Storage(connect=False)
        storage.client = mock_client

        # Test bucket_exists returns False for non-existent bucket
        assert not storage.bucket_exists("test-bucket")
        mock_client.head_bucket.assert_called_with(Bucket="test-test-bucket")

        # Test make_bucket creates bucket
        storage.make_bucket("test-bucket")
        mock_client.create_bucket.assert_called_with(Bucket="test-test-bucket")

    @patch("common.storage.boto3.client")
    def test_bucket_prefix(self, mock_boto3_client, mock_settings_minio):
        """Test bucket name prefix functionality."""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client
        mock_client.head_bucket.return_value = True

        storage = Storage(connect=False)
        storage.client = mock_client

        # Test _get_bucket_name applies prefix
        assert storage._get_bucket_name("photos") == "test-photos"
        assert storage._get_bucket_name("videos") == "test-videos"

    @patch("common.storage.boto3.client")
    def test_file_operations(self, mock_boto3_client, mock_settings_minio):
        """Test file upload, download, and delete operations."""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client

        storage = Storage(connect=False)
        storage.client = mock_client

        # Test file upload
        storage.fput_object("photos", "test.jpg", "/path/to/test.jpg", "image/jpeg")
        mock_client.upload_file.assert_called_with(
            "/path/to/test.jpg",
            "test-photos",
            "test.jpg",
            ExtraArgs={"ContentType": "image/jpeg"},
        )

        # Test file download
        mock_response = {"Body": Mock(), "ContentType": "image/jpeg"}
        mock_client.get_object.return_value = mock_response

        result = storage.get_object("photos", "test.jpg")
        mock_client.get_object.assert_called_with(Bucket="test-photos", Key="test.jpg")
        assert result == mock_response

        # Test file delete
        storage.remove_object("photos", "test.jpg")
        mock_client.delete_object.assert_called_with(
            Bucket="test-photos", Key="test.jpg"
        )

    @patch("common.storage.boto3.client")
    def test_error_handling(self, mock_boto3_client, mock_settings_minio):
        """Test error handling for various operations."""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client

        storage = Storage(connect=False)
        storage.client = mock_client

        # Test bucket_exists handles different error codes
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket"}}, "HeadBucket"
        )
        assert not storage.bucket_exists("nonexistent")

        # Test bucket_exists re-raises non-404 errors
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "HeadBucket"
        )
        with pytest.raises(ClientError):
            storage.bucket_exists("forbidden")

        # Test make_bucket handles BucketAlreadyOwnedByYou
        mock_client.create_bucket.side_effect = ClientError(
            {"Error": {"Code": "BucketAlreadyOwnedByYou"}}, "CreateBucket"
        )
        storage.make_bucket("existing")  # Should not raise

        # Test make_bucket re-raises other errors
        mock_client.create_bucket.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "CreateBucket"
        )
        with pytest.raises(ClientError):
            storage.make_bucket("forbidden")

    def test_storage_bucket_names_enum(self):
        """Test StorageBucketNames enum values."""
        assert StorageBucketNames.thumbnails == "thumbnails"
        assert StorageBucketNames.photos == "photos"
        assert StorageBucketNames.videos == "videos"
        assert StorageBucketNames.audios == "audios"
        assert StorageBucketNames.documents == "documents"
        assert StorageBucketNames.animations == "animations"
        assert StorageBucketNames.voices == "voices"
        assert StorageBucketNames.video_notes == "video-notes"
        assert StorageBucketNames.stickers == "stickers"

    @patch("common.storage.boto3.client")
    def test_endpoint_url_generation(self, mock_boto3_client, mock_settings_minio):
        """Test endpoint URL generation logic."""
        storage = Storage(connect=False)

        # Test HTTP prefix addition
        mock_settings_minio.storage_endpoint = "minio:9000"
        mock_settings_minio.storage_use_ssl = False
        assert storage._get_endpoint_url() == "http://minio:9000"

        # Test HTTPS prefix addition
        mock_settings_minio.storage_use_ssl = True
        assert storage._get_endpoint_url() == "https://minio:9000"

        # Test endpoint already has protocol
        mock_settings_minio.storage_endpoint = "https://my-minio.example.com"
        assert storage._get_endpoint_url() == "https://my-minio.example.com"

    @patch("common.storage.boto3.client")
    def test_automatic_bucket_creation(self, mock_boto3_client, mock_settings_minio):
        """Test that all required buckets are created automatically."""
        mock_client = Mock()
        mock_boto3_client.return_value = mock_client

        # Mock all buckets don't exist
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadBucket"
        )
        mock_client.create_bucket.return_value = None

        storage = Storage(connect=True)

        # Verify all bucket types were checked and created
        expected_buckets = [
            "test-thumbnails",
            "test-photos",
            "test-audios",
            "test-documents",
            "test-animations",
            "test-videos",
            "test-voices",
            "test-video-notes",
            "test-stickers",
        ]

        assert mock_client.head_bucket.call_count == len(expected_buckets)
        assert mock_client.create_bucket.call_count == len(expected_buckets)

        created_buckets = [
            call[1]["Bucket"] for call in mock_client.create_bucket.call_args_list
        ]
        assert set(created_buckets) == set(expected_buckets)
