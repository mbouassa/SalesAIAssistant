"""
Agent API endpoints.
Handles spawning and managing AI agents in rooms.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.daily_service import DailyService
from app.services.ai_agent import spawn_agent, remove_agent, get_agent


router = APIRouter(prefix="/agent", tags=["agent"])


class AgentJoinResponse(BaseModel):
    """Response when agent joins a room."""
    success: bool
    message: str
    room_name: str


class AgentStatusResponse(BaseModel):
    """Response for agent status check."""
    active: bool
    room_name: str


@router.post("/join/{room_name}", response_model=AgentJoinResponse)
async def join_room(room_name: str):
    """
    Spawn an AI agent to join the specified room.
    
    The agent will:
    1. Join the Daily room as a participant
    2. Listen to user speech (STT)
    3. Generate responses (LLM)
    4. Speak back (TTS)
    """
    # Clean up any existing agent first (handles refresh/reconnect cases)
    existing = get_agent(room_name)
    if existing:
        print(f"[Agent API] Removing existing agent for refresh/reconnect", flush=True)
        await remove_agent(room_name)
    
    try:
        # Get room info and create token for the agent
        daily_service = DailyService()
        room = await daily_service.get_room(room_name)
        
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        room_url = room.get("url", "")
        
        # Create a token for the AI agent
        token = await daily_service.create_meeting_token(
            room_name=room_name,
            user_name="AI Assistant",
            is_owner=False,
        )
        
        print(f"[Agent API] Room URL: {room_url}")
        print(f"[Agent API] Token created for AI Assistant")
        
        # Spawn the agent
        await spawn_agent(room_name, room_url, token)
        
        return AgentJoinResponse(
            success=True,
            message="Agent joining room",
            room_name=room_name,
        )
        
    except Exception as e:
        import traceback
        print(f"[Agent API] Error spawning agent: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/leave/{room_name}", response_model=AgentJoinResponse)
async def leave_room(room_name: str):
    """Remove the AI agent from the specified room."""
    agent = get_agent(room_name)
    
    if not agent:
        raise HTTPException(status_code=404, detail="No agent in this room")
    
    await remove_agent(room_name)
    
    return AgentJoinResponse(
        success=True,
        message="Agent left room",
        room_name=room_name,
    )


@router.get("/status/{room_name}", response_model=AgentStatusResponse)
async def get_status(room_name: str):
    """Check if an AI agent is active in the specified room."""
    agent = get_agent(room_name)
    
    return AgentStatusResponse(
        active=agent is not None,
        room_name=room_name,
    )

