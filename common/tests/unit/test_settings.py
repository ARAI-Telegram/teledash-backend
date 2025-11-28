import os

import pytest
from pydantic import ValidationError

from common.settings import Settings


class TestSettingsValidation:
    """Test cases for Settings validation logic."""

    def setup_method(self):  # is called automatically before each test method
        """Clear environment variables before each test to ensure isolation."""
        self.env_backup = {}
        storage_env_vars = [
            "STORAGE_PROVIDER",
            "STORAGE_REGION",
            "STORAGE_USE_SSL",
            "STORAGE_ENDPOINT",
            "STORAGE_ACCESS_KEY",
            "STORAGE_SECRET_KEY",
            "STORAGE_BUCKET_PREFIX",
            "JWT_SECRET",
            "JWT_LIFETIME_SECONDS",
            "FALLBACK_LANGUAGE",
            "COMPOSE_PROJECT_NAME",
        ]

        for var in storage_env_vars:
            if var in os.environ:
                self.env_backup[var] = os.environ[var]
                del os.environ[var]

    def teardown_method(self):
        """Restore environment variables after each test."""
        for var, value in self.env_backup.items():
            os.environ[var] = value

    def test_valid_aws_configuration(self):
        """Test valid AWS S3 configuration."""
        config = {
            "storage_provider": "aws",
            "storage_region": "us-east-1",
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        settings = Settings(**config)
        assert settings.storage_provider == "aws"
        assert settings.storage_region == "us-east-1"

    def test_valid_s3_compatible_configuration(self):
        """Test valid S3-compatible configuration."""
        config = {
            "storage_provider": "s3-compatible",
            "storage_endpoint": "minio:9000",
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        settings = Settings(**config)
        assert settings.storage_provider == "s3-compatible"
        assert settings.storage_endpoint == "minio:9000"

    def test_aws_missing_region_fails(self):
        """Test that AWS configuration without region fails validation."""
        config = {
            "storage_provider": "aws",
            # Missing storage_region
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        with pytest.raises(ValidationError) as exc_info:
            Settings(**config)

        assert "storage_region is required when using AWS provider" in str(
            exc_info.value
        )

    def test_aws_with_empty_region_fails(self):
        """Test that AWS configuration with empty region fails validation."""
        config = {
            "storage_provider": "aws",
            "storage_region": "",  # Empty region
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        with pytest.raises(ValidationError) as exc_info:
            Settings(**config)

        assert "storage_region is required when using AWS provider" in str(
            exc_info.value
        )

    def test_s3_compatible_without_region_succeeds(self):
        """Test that S3-compatible configuration without region succeeds."""
        config = {
            "storage_provider": "s3-compatible",
            "storage_endpoint": "r2.cloudflarestorage.com",
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        settings = Settings(**config)
        assert settings.storage_provider == "s3-compatible"
        assert settings.storage_region is None

    def test_invalid_provider_fails(self):
        """Test that invalid storage provider fails validation."""
        config = {
            "storage_provider": "invalid_provider",
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        with pytest.raises(ValidationError) as exc_info:
            Settings(**config)

        error_msg = str(exc_info.value)
        assert "storage_provider" in error_msg
        assert "invalid_provider" in error_msg

    def test_default_values(self):
        """Test default values are set correctly."""
        # Only provide required fields
        config = {
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",  # Explicitly set to avoid environment influence
        }
        settings = Settings(**config)

        # Check defaults
        assert settings.storage_provider == "s3-compatible"
        assert settings.storage_region is None
        assert settings.storage_use_ssl is False
        assert settings.storage_endpoint == "minio:9000"  # Default value
        assert settings.storage_bucket_prefix == ""
        assert settings.fallback_language == "en"

    def test_attachment_types_validation(self):
        """Test attachment types validation."""
        # Valid attachment types
        config = {
            "save_attachments": True,
            "save_attachment_types": ["photo", "video", "audio"],
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        settings = Settings(**config)
        assert settings.save_attachment_types == ["photo", "video", "audio"]

    def test_invalid_attachment_types_fails(self):
        """Test that invalid attachment types fail validation."""
        config = {
            "save_attachments": True,
            "save_attachment_types": ["photo", "invalid_type", "video"],
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        with pytest.raises(ValidationError) as exc_info:
            Settings(**config)

        error_msg = str(exc_info.value)
        assert "SAVE_ATTACHMENT_TYPES" in error_msg
        assert "invalid_type" in error_msg

    def test_bucket_prefix_applied(self):
        """Test bucket prefix configuration."""
        config = {
            "storage_bucket_prefix": "myapp-",
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        settings = Settings(**config)
        assert settings.storage_bucket_prefix == "myapp-"

    def test_ssl_configuration(self):
        """Test SSL configuration options."""
        # Test SSL enabled
        config = {
            "storage_use_ssl": True,
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        settings = Settings(**config)
        assert settings.storage_use_ssl is True

        # Test SSL disabled (default)
        config["storage_use_ssl"] = False
        settings = Settings(**config)
        assert settings.storage_use_ssl is False

    def test_hetzner_as_aws_provider(self):
        """Test Hetzner configured as AWS provider with custom endpoint."""
        config = {
            "storage_provider": "aws",
            "storage_region": "eu-central-1",
            "storage_endpoint": "fsn1.your-objectstorage.com",
            "storage_use_ssl": True,
            "storage_access_key": "hetzner_key",
            "storage_secret_key": "hetzner_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        settings = Settings(**config)
        assert settings.storage_provider == "aws"
        assert settings.storage_region == "eu-central-1"
        assert settings.storage_endpoint == "fsn1.your-objectstorage.com"
        assert settings.storage_use_ssl is True

    def test_cloudflare_r2_configuration(self):
        """Test Cloudflare R2 as S3-compatible provider."""
        config = {
            "storage_provider": "s3-compatible",
            "storage_endpoint": "account-id.r2.cloudflarestorage.com",
            "storage_use_ssl": True,
            "storage_access_key": "r2_key",
            "storage_secret_key": "r2_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        settings = Settings(**config)
        assert settings.storage_provider == "s3-compatible"
        assert settings.storage_endpoint == "account-id.r2.cloudflarestorage.com"
        assert settings.storage_region is None  # R2 doesn't use regions
        assert settings.storage_use_ssl is True

    def test_minio_configuration(self):
        """Test MinIO as S3-compatible provider."""
        config = {
            "storage_provider": "s3-compatible",
            "storage_endpoint": "minio:9000",
            "storage_use_ssl": False,
            "storage_access_key": "minio_user",
            "storage_secret_key": "minio_password",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": 3600,
            "fallback_language": "en",
        }
        settings = Settings(**config)
        assert settings.storage_provider == "s3-compatible"
        assert settings.storage_endpoint == "minio:9000"
        assert settings.storage_use_ssl is False

    def test_missing_required_fields_fails(self):
        """Test that missing required fields fail validation."""
        # Missing storage credentials should fail (env vars already cleared in setup_method)
        with pytest.raises(ValidationError) as exc_info:
            Settings()  # type: ignore # Intentionally missing required args for testing

        error_msg = str(exc_info.value)
        # Should fail on one of the required fields
        assert any(
            field in error_msg
            for field in ["storage_access_key", "storage_secret_key", "jwt_secret"]
        )

    def test_env_var_style_validation(self):
        """Test validation with environment variable style inputs."""
        # Test boolean strings (as they come from env vars)
        config = {
            "storage_use_ssl": "true",  # String instead of bool
            "save_attachments": "false",
            "storage_access_key": "test_key",
            "storage_secret_key": "test_secret",
            "jwt_secret": "test_jwt_secret",
            "jwt_lifetime_seconds": "3600",  # String instead of int
            "fallback_language": "en",
        }

        # Pydantic should handle type conversion
        settings = Settings(**config)  # type: ignore # Intentionally wrong types
        assert settings.storage_use_ssl is True
        assert settings.save_attachments is False
        assert settings.jwt_lifetime_seconds == 3600
