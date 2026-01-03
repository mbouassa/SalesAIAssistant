"""
LLM Service using OpenAI.
Handles conversation and response generation with persistent memory.
Supports function calling for browser control.
"""

import json
from typing import Optional, Callable, Any
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.memory_service import MemoryService


# Browser control tools for function calling
BROWSER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scroll_page",
            "description": "Scroll the product page up or down to show different sections",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "Direction to scroll"
                    }
                },
                "required": ["direction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click_element",
            "description": "Click a button or link on the page (e.g., 'Add to Cart', 'Learn More', 'See Features')",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_text": {
                        "type": "string",
                        "description": "The visible text of the button or link to click"
                    }
                },
                "required": ["element_text"]
            }
        }
    }
]


class LLMService:
    """OpenAI-based LLM service for conversation with memory and browser control."""
    
    SYSTEM_PROMPT = """You are a friendly AI sales assistant giving a live product demo. 
You can see and control a browser showing the product page.

Your job:
1. Guide the user through the product, highlighting key features
2. Answer questions about the product
3. Use browser actions to navigate and demonstrate (scroll to show features, click buttons)

Keep responses concise (1-2 sentences) since this is a real-time voice conversation.
Be enthusiastic but not pushy. When showing features, use scroll_page or click_element.

Available page elements: {clickable_elements}
"""
    
    SYSTEM_PROMPT_NO_BROWSER = """You are a friendly AI assistant in a video call demo. 
Have a natural, helpful conversation with the user. 
Keep your responses concise (1-2 sentences) since this is a real-time voice conversation.
Be warm, professional, and engaging."""
    
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-4.1-mini"
        self.memory: Optional[MemoryService] = None
        self.browser_enabled = False
        self.page_context: dict = {}
        self._action_handlers: dict[str, Callable] = {}
    
    def set_browser_context(self, page_context: dict, action_handlers: dict[str, Callable]) -> None:
        """Enable browser control with page context and action handlers."""
        self.browser_enabled = True
        self.page_context = page_context
        self._action_handlers = action_handlers
        print(f"[LLM] Browser context set: {page_context.get('title', 'Unknown page')}", flush=True)
    
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
        May trigger browser actions via function calling.
        
        Args:
            user_message: The transcribed user speech
            
        Returns:
            The AI's response text
        """
        # Save user message to memory
        if self.memory:
            await self.memory.add_message("user", user_message)
        
        # Build system prompt
        if self.browser_enabled:
            clickables = self.page_context.get("clickable_elements", [])
            clickable_text = ", ".join([el.get("text", "") for el in clickables[:10]])
            system_prompt = self.SYSTEM_PROMPT.format(clickable_elements=clickable_text or "None detected")
        else:
            system_prompt = self.SYSTEM_PROMPT_NO_BROWSER
        
        # Build messages with system prompt + history
        history = self.memory.get_messages_for_llm() if self.memory else []
        messages = [
            {"role": "system", "content": system_prompt},
            *history
        ]
        
        # Get completion from OpenAI (with tools if browser enabled)
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 150,
            "temperature": 0.7,
        }
        
        if self.browser_enabled:
            kwargs["tools"] = BROWSER_TOOLS
            kwargs["tool_choice"] = "auto"
        
        response = await self.client.chat.completions.create(**kwargs)
        
        message = response.choices[0].message
        
        # Handle function calls
        if message.tool_calls:
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)
                
                print(f"[LLM] Function call: {func_name}({func_args})", flush=True)
                
                # Execute the action
                if func_name in self._action_handlers:
                    await self._action_handlers[func_name](**func_args)
        
        # Extract response text
        assistant_message = message.content or ""
        
        # If only function call with no message, generate a follow-up
        if not assistant_message and message.tool_calls:
            assistant_message = "Let me show you that..."
        
        # Save assistant message to memory
        if self.memory and assistant_message:
            await self.memory.add_message("assistant", assistant_message)
        
        return assistant_message
    
    def reset_conversation(self) -> None:
        """Clear conversation history (local cache only)."""
        if self.memory:
            self.memory._messages_cache = []
