"""
Cloudflare R2 Storage Integration for Vault Graph

Read-only access to R2 for generating presigned download URLs.
"""
import logging
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class R2Storage:
    """
    Cloudflare R2 storage wrapper for presigned URL generation.

    This is a read-only wrapper - Vault Graph only needs to generate
    download URLs for documents stored by Context Vault.
    """

    def __init__(self, client=None, bucket_name: str = None, endpoint_url: str = None):
        """Initialize R2Storage."""
        self.client = client
        self.bucket_name = bucket_name if bucket_name is not None else settings.s3_bucket_name
        self.endpoint_url = endpoint_url if endpoint_url is not None else (settings.s3_endpoint_url or "")

    @property
    def is_configured(self) -> bool:
        """Check if storage is properly configured."""
        return self.client is not None and bool(self.bucket_name)

    def generate_presigned_url(
        self,
        key: str,
        expiration: int = None
    ) -> Optional[str]:
        """
        Generate a presigned URL for downloading a file.

        Args:
            key: S3 key of the object
            expiration: URL validity in seconds (default from settings)

        Returns:
            Presigned URL string or None if not configured
        """
        if not self.is_configured:
            return None

        if expiration is None:
            expiration = settings.presigned_url_expiration

        try:
            url = self.client.generate_presigned_url(
                ClientMethod='get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': key
                },
                ExpiresIn=expiration
            )
            logger.debug(f"Generated presigned URL for {key} (expires in {expiration}s)")
            return url

        except Exception as e:
            logger.error(f"Failed to generate presigned URL for {key}: {e}")
            return None

    def file_exists(self, key: str) -> bool:
        """Check if a file exists in R2."""
        if not self.is_configured:
            return False

        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except Exception:
            return False


def create_s3_client():
    """Create and return an S3 client configured for Cloudflare R2."""
    if not all([
        settings.s3_endpoint_url,
        settings.s3_access_key_id,
        settings.s3_secret_access_key,
        settings.s3_bucket_name
    ]):
        logger.warning("S3/R2 configuration incomplete - storage disabled")
        return None

    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            's3',
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=Config(
                signature_version='s3v4',
                retries={'max_attempts': 3, 'mode': 'standard'}
            )
        )

        logger.info(f"S3 client initialized: {settings.s3_endpoint_url}")
        return client

    except ImportError:
        logger.error("boto3 not installed - storage disabled")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {e}")
        return None


# Global storage instance
_s3_client = None
_storage = None


def get_storage() -> Optional[R2Storage]:
    """Get the global R2Storage instance."""
    global _s3_client, _storage

    if _storage is None:
        _s3_client = create_s3_client()
        if _s3_client:
            _storage = R2Storage(
                client=_s3_client,
                bucket_name=settings.s3_bucket_name,
                endpoint_url=settings.s3_endpoint_url
            )

    return _storage
