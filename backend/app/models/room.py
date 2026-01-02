"""
Room models for Daily.co integration.
"""

from datetime import datetime
from pydantic import BaseModel, Field


class RoomCreateRequest(BaseModel):
    """Request body for creating a new room."""
    
    name: str | None = Field(
        default=None,
        description="Optional room name. If not provided, Daily.co generates one."
    )
    privacy: str = Field(
        default="private",
        description="Room privacy: 'public' or 'private'"
    )
    expires_in_minutes: int = Field(
        default=60,
        ge=1,
        le=1440,
        description="Room expiration time in minutes (1-1440)"
    )


class RoomResponse(BaseModel):
    """Response containing room details."""
    
    id: str
    name: str
    url: str
    privacy: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class RoomTokenRequest(BaseModel):
    """Request body for creating a meeting token."""
    
    room_name: str = Field(..., description="Name of the room to create token for")
    user_name: str = Field(..., description="Display name for the participant")
    is_owner: bool = Field(
        default=False,
        description="Whether this participant has owner privileges"
    )
    expires_in_minutes: int = Field(
        default=60,
        ge=1,
        le=1440,
        description="Token expiration time in minutes"
    )


class RoomTokenResponse(BaseModel):
    """Response containing the meeting token."""
    
    token: str
    room_url: str

