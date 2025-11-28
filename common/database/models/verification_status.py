from typing import Optional

from pydantic import BaseModel


class VerificationStatus(BaseModel):
    """Contains information about verification status of a chat or a user."""

    is_verified: Optional[bool] = None
    is_scam: Optional[bool] = None
    is_fake: Optional[bool] = None
