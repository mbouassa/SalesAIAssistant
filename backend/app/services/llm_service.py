"""
LLM Service using OpenAI.
Handles conversation and response generation with persistent memory.
"""

from typing import Optional
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.memory_service import MemoryService


class LLMService:
    """OpenAI-based LLM service for conversation with memory."""
    
    SYSTEM_PROMPT = """You are a friendly AI assistant in a video call demo. 
Have a natural, helpful conversation with the user. 
Keep your responses concise (1-2 sentences) since this is a real-time voice conversation.
Be warm, professional, and engaging."""
    
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-4o-mini"
        self.memory: Optional[MemoryService] = None
    
    async def set_room(self, room_name: str) -> None:
        """Set the room and load conversation history."""
        self.memory = MemoryService(room_name)
        await self.memory.load_history()
        
        msg_count = len(self.memory.get_messages_for_llm())
        if msg_count > 0:
            print(f"[LLM] Loaded {msg_count} messages from previous conversation", flush=True)
    
    async def get_response(self, user_message: str) -> str:
        """
        Generate a response to the user's message.
        
        Args:
            user_message: The transcribed user speech
            
        Returns:
            The AI's response text
        """
        # Save user message to memory
        if self.memory:
            await self.memory.add_message("user", user_message)
        
        # Build messages with system prompt + history
        history = self.memory.get_messages_for_llm() if self.memory else []
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            *history
        ]
        
        # Get completion from OpenAI
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=150,
            temperature=0.7,
        )
        
        # Extract response text
        assistant_message = response.choices[0].message.content or ""
        
        # Save assistant message to memory
        if self.memory:
            await self.memory.add_message("assistant", assistant_message)
        
        return assistant_message
    
    def reset_conversation(self) -> None:
        """Clear conversation history (local cache only)."""
        if self.memory:
            self.memory._messages_cache = []
