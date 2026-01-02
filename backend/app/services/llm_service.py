"""
LLM Service using OpenAI.
Handles conversation and response generation.
"""

from openai import AsyncOpenAI

from app.core.config import get_settings


class LLMService:
    """OpenAI-based LLM service for conversation."""
    
    SYSTEM_PROMPT = """You are a friendly AI assistant in a video call demo. 
Have a natural, helpful conversation with the user. 
Keep your responses concise (1-2 sentences) since this is a real-time voice conversation.
Be warm, professional, and engaging."""
    
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.conversation_history: list[dict] = []
        self.model = "gpt-4o-mini"
    
    async def get_response(self, user_message: str) -> str:
        """
        Generate a response to the user's message.
        
        Args:
            user_message: The transcribed user speech
            
        Returns:
            The AI's response text
        """
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })
        
        # Build messages with system prompt
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            *self.conversation_history
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
        
        # Add to history
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })
        
        return assistant_message
    
    def reset_conversation(self) -> None:
        """Clear conversation history."""
        self.conversation_history = []

