"""
Agent API endpoints.
Handles spawning and managing AI agents in rooms.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.daily_service import DailyService
from app.services.ai_agent import spawn_agent, remove_agent, get_agent
from app.services.browser_service import browser_service
from app.services.perception_service import perception_service
from app.api.v1.rooms import get_room_metadata


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
        # Get room metadata (company_id for persona)
        metadata = get_room_metadata(room_name)
        company_id = metadata.get("company_id")
        if company_id:
            print(f"[Agent API] Using company persona: {company_id}", flush=True)
        
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
        
        # Spawn the agent with company persona
        await spawn_agent(room_name, room_url, token, company_id=company_id)
        
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


@router.get("/perception/{room_name}")
async def get_perception(room_name: str):
    """
    Test endpoint: Extract and return page state from browser session.
    
    Use this to verify Perception Service is working correctly.
    """
    session = browser_service.get_session(room_name)
    
    if not session or not session.page:
        raise HTTPException(status_code=404, detail="No browser session for this room")
    
    # Extract page state
    state = await perception_service.extract(session.page)
    
    # Return as dict for JSON serialization
    return {
        "url": state.url,
        "domain": state.domain,
        "title": state.title,
        "text_summary_length": len(state.text_summary),
        "text_preview": state.text_summary[:300] + "..." if len(state.text_summary) > 300 else state.text_summary,
        "headings": [{"level": h.level, "text": h.text} for h in state.headings],
        "clickables_count": len(state.clickables),
        "clickables": [
            {"role": c.role, "name": c.name, "selector": c.selector[:50]}
            for c in state.clickables[:15]
        ],
        "inputs_count": len(state.inputs),
        "inputs": [
            {"type": i.input_type, "name": i.name}
            for i in state.inputs
        ],
        "extraction_time_ms": state.extraction_time_ms,
        "llm_summary": perception_service.summarize_for_llm(state)
    }

