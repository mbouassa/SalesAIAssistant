"""
Daily.co API service.
Handles all interactions with the Daily.co REST API.
"""

import httpx
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import get_settings


class DailyService:
    """Service for interacting with Daily.co API."""
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.daily_api_url
        self.headers = {
            "Authorization": f"Bearer {self.settings.daily_api_key}",
            "Content-Type": "application/json"
        }
    
    async def create_room(
        self,
        name: str | None = None,
        privacy: str = "private",
        expires_in_minutes: int = 60
    ) -> dict[str, Any]:
        """
        Create a new Daily.co room.
        
        Args:
            name: Optional room name. If None, Daily.co generates one.
            privacy: 'public' or 'private'
            expires_in_minutes: How long until the room expires
            
        Returns:
            Room details from Daily.co API
        """
        expiration = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
        
        payload: dict[str, Any] = {
            "privacy": privacy,
            "properties": {
                "exp": int(expiration.timestamp()),
                "enable_chat": True,
                "enable_screenshare": True,
                "start_video_off": True,
                "start_audio_off": False,
            }
        }
        
        if name:
            payload["name"] = name
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/rooms",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            return response.json()
    
    async def get_room(self, room_name: str) -> dict[str, Any]:
        """
        Get details of an existing room.
        
        Args:
            room_name: The name of the room
            
        Returns:
            Room details from Daily.co API
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/rooms/{room_name}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def delete_room(self, room_name: str) -> bool:
        """
        Delete a room.
        
        Args:
            room_name: The name of the room to delete
            
        Returns:
            True if deleted successfully
        """
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.base_url}/rooms/{room_name}",
                headers=self.headers
            )
            response.raise_for_status()
            return True
    
    async def create_meeting_token(
        self,
        room_name: str,
        user_name: str,
        is_owner: bool = False,
        expires_in_minutes: int = 60
    ) -> str:
        """
        Create a meeting token for joining a room.
        
        Args:
            room_name: Name of the room
            user_name: Display name for the participant
            is_owner: Whether participant has owner privileges
            expires_in_minutes: Token expiration time
            
        Returns:
            Meeting token string
        """
        expiration = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
        
        payload = {
            "properties": {
                "room_name": room_name,
                "user_name": user_name,
                "is_owner": is_owner,
                "exp": int(expiration.timestamp()),
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/meeting-tokens",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            return data["token"]


# Singleton instance
daily_service = DailyService()

