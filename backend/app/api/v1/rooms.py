"""
Room API endpoints.
Handles room creation, retrieval, and token generation.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status

from app.models.room import (
    RoomCreateRequest,
    RoomResponse,
    RoomTokenRequest,
    RoomTokenResponse,
)
from app.services.daily_service import daily_service


router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
async def create_room(request: RoomCreateRequest) -> RoomResponse:
    """
    Create a new Daily.co room for a demo session.
    
    Returns the room details including the join URL.
    """
    try:
        room_data = await daily_service.create_room(
            name=request.name,
            privacy=request.privacy,
            expires_in_minutes=request.expires_in_minutes
        )
        
        return RoomResponse(
            id=room_data["id"],
            name=room_data["name"],
            url=room_data["url"],
            privacy=room_data["privacy"],
            created_at=datetime.fromisoformat(
                room_data["created_at"].replace("Z", "+00:00")
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create room: {str(e)}"
        )


@router.get("/{room_name}", response_model=RoomResponse)
async def get_room(room_name: str) -> RoomResponse:
    """
    Get details of an existing room.
    """
    try:
        room_data = await daily_service.get_room(room_name)
        
        return RoomResponse(
            id=room_data["id"],
            name=room_data["name"],
            url=room_data["url"],
            privacy=room_data["privacy"],
            created_at=datetime.fromisoformat(
                room_data["created_at"].replace("Z", "+00:00")
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room not found: {str(e)}"
        )


@router.delete("/{room_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(room_name: str) -> None:
    """
    Delete a room.
    """
    try:
        await daily_service.delete_room(room_name)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to delete room: {str(e)}"
        )


@router.post("/token", response_model=RoomTokenResponse)
async def create_token(request: RoomTokenRequest) -> RoomTokenResponse:
    """
    Create a meeting token for joining a room.
    
    Tokens are required for private rooms and provide
    participant identity and permissions.
    """
    try:
        # First verify the room exists
        room_data = await daily_service.get_room(request.room_name)
        
        token = await daily_service.create_meeting_token(
            room_name=request.room_name,
            user_name=request.user_name,
            is_owner=request.is_owner,
            expires_in_minutes=request.expires_in_minutes
        )
        
        return RoomTokenResponse(
            token=token,
            room_url=room_data["url"]
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create token: {str(e)}"
        )

