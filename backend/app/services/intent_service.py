"""
Intent Detection Service - LLM-based intent classification.

Extracted from ai_agent.py for better modularity.
All methods are stateless LLM calls that classify user intent.
"""

import json
from typing import Optional
from openai import AsyncOpenAI
from app.core.config import get_settings


class IntentService:
    """
    Service for detecting user intents using LLM.
    
    All methods are stateless - they take input and return classification results.
    This service handles:
    - Closing intent detection
    - Demo/tour request detection
    - Affirmative response detection
    - Follow-up need detection
    - Home page detection
    """
    
    def __init__(self):
        """Initialize IntentService with OpenAI client."""
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-4.1"
    
    async def check_closing_intent(
        self, 
        user_message: str, 
        conversation_history: list
    ) -> bool:
        """
        Detect if user is signaling they're done with the demo/conversation.
        
        Examples: "all good", "that's all", "I've seen enough", "no thanks"
        
        Args:
            user_message: The user's latest message
            conversation_history: Recent conversation messages
            
        Returns:
            bool: True if user wants to end conversation
        """
        # Format recent history
        history = conversation_history[-4:] if conversation_history else []
        history_str = "\n".join([
            f"{'AI' if m.get('role') == 'assistant' else 'User'}: {m.get('content', '')[:100]}"
            for m in history
        ])
        
        prompt = f"""Determine if the user is signaling they are DONE with the conversation/demo and ready to wrap up.

RECENT CONVERSATION:
{history_str}

USER'S LATEST MESSAGE: "{user_message}"

Closing signals include:
- "all good", "that's all", "I'm good", "no thanks"
- "I've seen enough", "that's it for me"
- "no more questions", "I think I'm done"
- Polite declines to see more features

NOT closing signals:
- Asking questions about features
- Requesting to see something else
- "Sure" or "yes" (agreeing to continue)
- Any request for more information

Is the user signaling they want to END the conversation? Answer ONLY "yes" or "no"."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0
            )
            
            answer = response.choices[0].message.content.strip().lower()
            is_closing = answer == "yes"
            print(f"[Intent] 👋 Closing check: '{user_message[:30]}...' → {is_closing}", flush=True)
            return is_closing
            
        except Exception as e:
            print(f"[Intent] Closing check error: {e}", flush=True)
            return False
    
    async def check_demo_intent(
        self, 
        user_message: str, 
        conversation_history: list
    ) -> bool:
        """
        Check if user wants a FULL product demo/tour.
        
        Args:
            user_message: The user's message
            conversation_history: Recent conversation for context
            
        Returns:
            bool: True if user wants a full demo
        """
        # Format recent conversation
        history_text = ""
        for msg in conversation_history[-6:]:  # Last 3 exchanges
            role = "AI" if msg.get("role") == "assistant" else "User"
            content = msg.get("content", "")[:100]
            history_text += f"{role}: {content}\n"
        
        prompt = f"""Determine if the user wants a FULL product demo or tour (showing ALL features).

RECENT CONVERSATION:
{history_text}
User: {user_message}

EXAMPLES OF YES (start demo):
- AI: "Do you want me to give you a quick tour?" → User: "Sure. Yeah." → YES
- AI: "Ready for a demo?" → User: "Yes please" → YES
- User: "Give me a full demo" → YES
- User: "Show me everything" → YES

EXAMPLES OF NO (do NOT start demo):
- User: "Awesome. Thank you so much." → NO (just thanking, not requesting demo)
- User: "Take me to the meditation screen" → NO (navigation to SPECIFIC screen)
- User: "Show me the journaling section" → NO (asking about ONE feature)
- User: "Could you take me to X again?" → NO (navigation request)
- User: "Thanks, that was great" → NO (gratitude, not a demo request)
- User: "Sorry, could you show me X?" → NO (specific feature request)
- AI: "Want me to walk you through this section?" → User: "Yeah" → NO (about THIS section only)

STRICT RULES:
1. Answer "yes" ONLY if user explicitly asks for a FULL tour/demo OR accepts an AI offer for a FULL tour
2. Answer "no" for thank you messages, gratitude, or appreciation
3. Answer "no" for requests to go to a SPECIFIC screen/feature/section
4. Answer "no" for navigation requests like "take me to X" or "show me X"
5. When in doubt, answer "no"

Answer ONLY "yes" or "no"."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0
            )
            answer = response.choices[0].message.content.strip().lower()
            print(f"[Intent] 🎬 Demo check: '{user_message[:30]}' (history: {len(conversation_history)} msgs) → {answer}", flush=True)
            return answer == "yes"
        except Exception as e:
            print(f"[Intent] ⚠️ Demo check error: {e}", flush=True)
            return False
    
    async def check_affirmative_response(self, user_message: str) -> bool:
        """
        Check if user's response is affirmative (for scheduling confirmation).
        
        Args:
            user_message: The user's response
            
        Returns:
            bool: True if affirmative
        """
        prompt = f"""The AI just asked the user if they'd like to schedule a call with the founder.

User's response: "{user_message}"

Is this an affirmative response (yes, they want to schedule)?

Respond with ONLY "yes" or "no"."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0
            )
            answer = response.choices[0].message.content.strip().lower()
            print(f"[Intent] 🤔 Affirmative check: '{user_message}' -> {answer}", flush=True)
            return answer == "yes"
        except Exception as e:
            print(f"[Intent] ⚠️ Affirmative check error: {e}", flush=True)
            return False
    
    async def check_needs_follow_up(
        self, 
        user_message: str, 
        target_section: str,
        page_text: str
    ) -> dict:
        """
        Determine if user needs a follow-up explanation after navigation.
        
        Args:
            user_message: Original user message
            target_section: Section we navigated to
            page_text: Current page content
            
        Returns:
            dict with 'needs_response' (bool) and 'topic' (str)
        """
        prompt = f"""After navigating to the "{target_section}" section, does the user need a spoken explanation?

USER'S ORIGINAL MESSAGE: "{user_message}"

PAGE CONTENT (what's now visible):
{page_text[:1000]}

Determine:
1. Did the user just want to be taken somewhere? (e.g., "take me to X", "go to X", "show me X")
   → No explanation needed, they can see it now.

2. Did the user ask a question or want something explained? (e.g., "explain X", "how does X work", "what is X", "tell me about X", "I'm confused about X")
   → Explanation IS needed.

OUTPUT JSON:
{{
    "needs_response": true or false,
    "reason": "brief reason",
    "topic": "what to explain (if needed)"
}}

Only output valid JSON."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content or "{}")
            return result
            
        except Exception as e:
            print(f"[Intent] Follow-up check error: {e}", flush=True)
            return {"needs_response": False}
    
    async def check_if_on_home_page(
        self,
        page_text: str,
        home_page_description: str
    ) -> bool:
        """
        Determine if current page is the home page.
        
        Args:
            page_text: Current page content
            home_page_description: Description of what home page looks like
            
        Returns:
            bool: True if on home page
        """
        if not home_page_description:
            return True
        
        prompt = f"""Compare the current page content to the home page description and determine if we're on the home page.

HOME PAGE DESCRIPTION:
{home_page_description}

CURRENT PAGE CONTENT:
{page_text[:1500]}

Question: Based on the content, is the user currently on the home page described above?

Answer with ONLY "yes" or "no" (lowercase, nothing else)."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0
            )
            
            answer = response.choices[0].message.content.strip().lower()
            is_home = answer == "yes"
            
            print(f"[Intent] 🏠 Home page check: '{answer}' → {is_home}", flush=True)
            return is_home
            
        except Exception as e:
            print(f"[Intent] ⚠️ Home page check failed: {e}", flush=True)
            return True  # Assume home on error

