"""
Presenter Service - The "face" of the AI agent.

Handles:
- Persona management (tone, style, personality)
- Natural language generation for demos
- Company-specific customization
- Context-aware response generation

The Presenter decides WHAT to say, not HOW to say it (that's TTS).
"""

import logging
import yaml
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field
from openai import AsyncOpenAI

from app.core.config import get_settings

# Configure logging with detailed format
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create console handler if not exists
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [Presenter] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


@dataclass
class Persona:
    """AI persona configuration."""
    name: str = "Demo Assistant"
    company: str = "Generic"
    role: str = "AI Sales Assistant"
    tone: str = "friendly, professional, enthusiastic"
    speaking_style: str = "concise and conversational"
    product_name: str = "the product"
    product_description: str = "an innovative solution"
    key_features: list[str] = field(default_factory=list)
    value_propositions: list[str] = field(default_factory=list)
    common_objections: dict[str, str] = field(default_factory=dict)
    demo_intro: str = "Hi! I'm excited to show you around today."
    demo_outro: str = "Thanks for checking this out! Any questions?"
    site_map: list[dict] = field(default_factory=list)  # Navigation structure for intent-based nav
    home_url: str = ""  # Home/dashboard URL - the only URL needed for navigation
    
    @classmethod
    def from_yaml(cls, path: Path) -> "Persona":
        """Load persona from YAML config file."""
        logger.debug(f"Loading persona from: {path}")
        try:
            with open(path, 'r') as f:
                data = yaml.safe_load(f)
            
            # Handle empty or invalid YAML files
            if not data or not isinstance(data, dict):
                logger.warning(f"Persona file is empty or invalid: {path}, using defaults")
                return cls()
            
            persona = cls(**data)
            logger.info(f"✓ Loaded persona: {persona.name} ({persona.company})")
            return persona
        except FileNotFoundError:
            logger.warning(f"Persona file not found: {path}, using defaults")
            return cls()
        except Exception as e:
            logger.error(f"Error loading persona: {e}")
            return cls()


class PresenterService:
    """
    Generates contextual, persona-aware responses for the AI agent.
    
    The Presenter is the "brain" that decides what the AI should say,
    taking into account:
    - Current page/context state
    - User's question/intent
    - Demo flow stage
    - Persona configuration
    """
    
    def __init__(self, company_id: Optional[str] = None):
        """
        Initialize the Presenter with optional company-specific persona.
        
        Args:
            company_id: Company identifier to load specific persona config
        """
        logger.info(f"Initializing PresenterService (company={company_id or 'default'})")
        
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-4.1-mini"
        
        # Load persona
        self.persona = self._load_persona(company_id)
        
        # Demo state tracking
        self.demo_stage = "intro"  # intro, exploring, deep_dive, closing
        self.features_shown: list[str] = []
        self.user_interests: list[str] = []
        self.objections_raised: list[str] = []
        
        # Page context (updated by perception)
        self.current_page_state: dict = {}
        
        logger.debug(f"Presenter ready with persona: {self.persona.name}")
    
    def _load_persona(self, company_id: Optional[str]) -> Persona:
        """Load company-specific persona or default."""
        if not company_id:
            logger.debug("No company_id provided, using default persona")
            return Persona()
        
        # Look for persona config in personas directory
        personas_dir = Path(__file__).parent.parent / "personas"
        persona_file = personas_dir / f"{company_id}.yaml"
        
        if persona_file.exists():
            return Persona.from_yaml(persona_file)
        else:
            logger.warning(f"No persona found for company '{company_id}', using default")
            return Persona()
    
    def update_page_context(self, page_state: dict) -> None:
        """
        Update the current page context from perception service.
        
        Args:
            page_state: DOM state from PerceptionService
        """
        old_url = self.current_page_state.get("url", "")
        new_url = page_state.get("url", "")
        
        self.current_page_state = page_state
        
        if old_url != new_url:
            logger.info(f"📍 Page changed: {new_url}")
            logger.debug(f"Page title: {page_state.get('title', 'Unknown')}")
            logger.debug(f"Clickable elements: {len(page_state.get('clickable_elements', []))}")
            logger.debug(f"Sections: {[s.get('heading', 'untitled') for s in page_state.get('sections', [])]}")
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt based on persona and context."""
        logger.debug("Building system prompt...")
        
        # Base persona instructions
        prompt_parts = [
            f"You are {self.persona.name}, a {self.persona.role} for {self.persona.company}.",
            f"Your tone is {self.persona.tone}.",
            f"Your speaking style is {self.persona.speaking_style}.",
            "",
            f"You're giving a live demo of {self.persona.product_name}: {self.persona.product_description}",
            "",
        ]
        
        # Add key features if available
        if self.persona.key_features:
            prompt_parts.append("Key features to highlight:")
            for feature in self.persona.key_features:
                prompt_parts.append(f"  - {feature}")
            prompt_parts.append("")
        
        # Add value propositions
        if self.persona.value_propositions:
            prompt_parts.append("Value propositions:")
            for prop in self.persona.value_propositions:
                prompt_parts.append(f"  - {prop}")
            prompt_parts.append("")
        
        # Add current page context
        if self.current_page_state:
            prompt_parts.append("CURRENT PAGE STATE:")
            prompt_parts.append(f"  URL: {self.current_page_state.get('url', 'Unknown')}")
            prompt_parts.append(f"  Title: {self.current_page_state.get('title', 'Unknown')}")
            
            # Add visible sections
            sections = self.current_page_state.get("sections", [])
            if sections:
                prompt_parts.append("  Visible sections:")
                for section in sections[:5]:  # Limit to 5
                    heading = section.get("heading", "")
                    if heading:
                        prompt_parts.append(f"    - {heading}")
            
            # Add clickable elements
            clickables = self.current_page_state.get("clickable_elements", [])
            if clickables:
                prompt_parts.append("  Available actions (buttons/links):")
                for el in clickables[:10]:  # Limit to 10
                    text = el.get("text", el.get("aria_label", ""))
                    if text:
                        prompt_parts.append(f"    - {text}")
            prompt_parts.append("")
        
        # Add demo state context
        prompt_parts.append(f"Demo stage: {self.demo_stage}")
        if self.features_shown:
            prompt_parts.append(f"Features already shown: {', '.join(self.features_shown)}")
        if self.user_interests:
            prompt_parts.append(f"User seems interested in: {', '.join(self.user_interests)}")
        
        # Add behavior guidelines
        prompt_parts.extend([
            "",
            "GUIDELINES:",
            "- Keep responses SHORT (1-2 sentences max) - this is voice, not text",
            "- Be natural and conversational, not robotic",
            "- When you want to show something, describe what you're about to do",
            "- React to user questions naturally before answering",
            "- Don't repeat yourself or over-explain",
            "- If asked about pricing, be helpful but redirect to the demo",
        ])
        
        prompt = "\n".join(prompt_parts)
        logger.debug(f"System prompt built ({len(prompt)} chars)")
        return prompt
    
    async def generate_intro(self) -> str:
        """Generate the demo introduction."""
        logger.info("🎬 Generating demo intro...")
        self.demo_stage = "intro"
        
        # Use persona's intro or generate one
        if self.persona.demo_intro:
            intro = self.persona.demo_intro
            logger.debug(f"Using persona intro: {intro[:50]}...")
            return intro
        
        # Generate dynamic intro
        response = await self._generate_response(
            context="Generate a brief, friendly introduction to start the product demo.",
            user_input=""
        )
        logger.info(f"Generated intro: {response[:50]}...")
        return response
    
    async def generate_response(
        self,
        user_input: str,
        action_result: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None
    ) -> str:
        """
        Generate a contextual response to user input.
        
        Args:
            user_input: What the user said (transcribed)
            action_result: Result of any action just performed (e.g., "scrolled down")
            conversation_history: Previous messages for context
            
        Returns:
            Natural language response for TTS
        """
        logger.info(f"💬 Generating response to: '{user_input[:50]}...' " if len(user_input) > 50 else f"💬 Generating response to: '{user_input}'")
        
        # Track user interests based on keywords
        self._track_user_interest(user_input)
        
        # Build context for LLM
        context_parts = []
        
        if action_result:
            context_parts.append(f"You just performed this action: {action_result}")
            logger.debug(f"Action context: {action_result}")
        
        # Detect objections
        objection_response = self._check_objection(user_input)
        if objection_response:
            context_parts.append(f"The user raised a common objection. Suggested response approach: {objection_response}")
            logger.debug(f"Objection detected, suggested approach: {objection_response[:50]}...")
        
        context = "\n".join(context_parts) if context_parts else None
        
        response = await self._generate_response(
            context=context,
            user_input=user_input,
            history=conversation_history
        )
        
        logger.info(f"✓ Generated response ({len(response)} chars): {response[:80]}...")
        return response
    
    async def generate_action_narration(self, action: str, target: str) -> str:
        """
        Generate natural speech to narrate an action being performed.
        
        Args:
            action: The action type (scroll, click, navigate)
            target: The target of the action
            
        Returns:
            Natural narration like "Let me scroll down to show you..."
        """
        logger.debug(f"Generating narration for: {action} -> {target}")
        
        narrations = {
            "scroll_down": [
                f"Let me scroll down to show you more.",
                f"Scrolling to the next section.",
                f"There's more below, let me show you.",
            ],
            "scroll_up": [
                f"Let me scroll back up.",
                f"Going back to the top.",
            ],
            "click": [
                f"Let me click on {target}.",
                f"I'll show you what happens when we click {target}.",
                f"Clicking {target} now.",
            ],
            "navigate": [
                f"Taking you to {target}.",
                f"Let's check out {target}.",
            ],
        }
        
        import random
        options = narrations.get(action, [f"Let me show you {target}."])
        narration = random.choice(options)
        
        logger.debug(f"Narration: {narration}")
        return narration
    
    async def generate_feature_highlight(self, feature_name: str, feature_details: dict) -> str:
        """
        Generate speech to highlight a specific feature.
        
        Args:
            feature_name: Name of the feature
            feature_details: Details from page context about the feature
            
        Returns:
            Natural feature explanation
        """
        logger.info(f"🌟 Highlighting feature: {feature_name}")
        
        # Track that we've shown this feature
        if feature_name not in self.features_shown:
            self.features_shown.append(feature_name)
        
        context = f"Highlight this feature naturally: {feature_name}"
        if feature_details:
            context += f"\nDetails: {feature_details}"
        
        response = await self._generate_response(
            context=context,
            user_input=""
        )
        
        logger.debug(f"Feature highlight: {response}")
        return response
    
    async def _generate_response(
        self,
        context: Optional[str],
        user_input: str,
        history: Optional[list[dict]] = None
    ) -> str:
        """Internal method to call LLM."""
        logger.debug("Calling LLM...")
        
        messages = [
            {"role": "system", "content": self._build_system_prompt()}
        ]
        
        # Add conversation history
        if history:
            messages.extend(history[-10:])  # Last 10 messages
            logger.debug(f"Added {min(len(history), 10)} history messages")
        
        # Add context if provided
        if context:
            messages.append({
                "role": "system", 
                "content": f"Additional context: {context}"
            })
        
        # Add user input
        if user_input:
            messages.append({"role": "user", "content": user_input})
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=100,  # Keep responses short for voice
                temperature=0.8,  # Slightly creative
            )
            
            result = response.choices[0].message.content or ""
            logger.debug(f"LLM response received ({len(result)} chars)")
            return result
            
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return "I'm having a bit of trouble. Could you repeat that?"
    
    def _track_user_interest(self, user_input: str) -> None:
        """Track what the user seems interested in."""
        lower_input = user_input.lower()
        
        interest_keywords = {
            "pricing": ["price", "cost", "how much", "expensive", "afford"],
            "features": ["feature", "can it", "does it", "capability"],
            "integration": ["integrate", "api", "connect", "work with"],
            "security": ["secure", "security", "safe", "privacy", "data"],
            "support": ["support", "help", "customer service"],
            "comparison": ["compare", "vs", "versus", "better than", "different from"],
        }
        
        for interest, keywords in interest_keywords.items():
            if any(kw in lower_input for kw in keywords):
                if interest not in self.user_interests:
                    self.user_interests.append(interest)
                    logger.info(f"📊 Tracked user interest: {interest}")
    
    def _check_objection(self, user_input: str) -> Optional[str]:
        """Check if user raised a common objection."""
        lower_input = user_input.lower()
        
        for objection, response_approach in self.persona.common_objections.items():
            if objection.lower() in lower_input:
                if objection not in self.objections_raised:
                    self.objections_raised.append(objection)
                    logger.info(f"⚠️ Objection detected: {objection}")
                return response_approach
        
        return None
    
    def advance_demo_stage(self, new_stage: str) -> None:
        """Advance the demo to a new stage."""
        old_stage = self.demo_stage
        self.demo_stage = new_stage
        logger.info(f"🎭 Demo stage: {old_stage} → {new_stage}")
    
    def get_demo_summary(self) -> dict:
        """Get a summary of the demo session."""
        summary = {
            "stage": self.demo_stage,
            "features_shown": self.features_shown,
            "user_interests": self.user_interests,
            "objections_raised": self.objections_raised,
            "persona": self.persona.name,
            "company": self.persona.company,
        }
        logger.debug(f"Demo summary: {summary}")
        return summary

