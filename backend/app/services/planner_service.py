"""
Planner Service - The decision-making brain of the AI agent.

Decides WHAT to do next based on:
- User input (transcribed speech)
- Current page state (from Perception)
- Demo context (stage, history)
- Site map (known navigation structure)
- Available actions

Outputs a structured plan: action, speech, or both.
"""

import json
import logging
from typing import Optional, Literal
from dataclasses import dataclass, field, asdict
from openai import AsyncOpenAI

from app.core.config import get_settings


def match_site_section(user_message: str, site_map: list[dict]) -> Optional[dict]:
    """
    Match user intent to a site section using keywords.
    
    Only matches for NAVIGATION requests, not specific element clicks.
    
    Args:
        user_message: What the user said
        site_map: List of sections with keywords
        
    Returns:
        Matching section dict or None
    """
    if not site_map:
        return None
    
    lower_message = user_message.lower()
    
    # Don't match if user is asking to click a specific element (not navigation)
    # Phrases like "click on the X button" or "click the download icon" are direct clicks
    specific_click_patterns = [
        "click on the", "click the", "press the", "tap the",
        "button with", "icon with", "that button", "this button"
    ]
    if any(pattern in lower_message for pattern in specific_click_patterns):
        return None  # Let the Planner handle this as a direct click
    
    best_match = None
    best_score = 0
    
    for section in site_map:
        keywords = section.get("keywords", [])
        # Count how many keywords match
        score = sum(1 for kw in keywords if kw.lower() in lower_message)
        
        if score > best_score:
            best_score = score
            best_match = section
    
    if best_match and best_score > 0:
        return best_match
    
    return None

# Configure logging with detailed format
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [Planner] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


@dataclass
class BrowserAction:
    """A browser action to perform."""
    action_type: Literal["scroll", "click", "navigate", "go_back", "wait", "none"]
    target: Optional[str] = None  # selector, direction, or URL
    description: str = ""  # human-readable description
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass 
class Plan:
    """The planner's decision output."""
    
    # Decision type
    decision: Literal["speak_only", "action_only", "action_then_speak", "speak_then_action"]
    
    # What to do (if any action) - ONE action at a time for step-by-step execution
    action: Optional[BrowserAction] = None
    actions: list[BrowserAction] = field(default_factory=list)  # Kept for backwards compat
    
    # What to say (actual speech text, not just intent)
    speech: str = ""
    speech_intent: str = ""  # Keep for backwards compat
    
    # Navigation context
    current_location: str = ""  # Where user is now
    target_location: str = ""   # Where user wants to go
    
    # Step-by-step execution
    needs_more_steps: bool = False  # True if more actions needed after this one
    goal_description: str = ""  # What we're trying to achieve
    
    # Why this decision was made (for debugging)
    reasoning: str = ""
    
    # Confidence score (0-1)
    confidence: float = 0.0
    
    def to_dict(self) -> dict:
        result = {
            "decision": self.decision,
            "speech": self.speech,
            "speech_intent": self.speech_intent,
            "current_location": self.current_location,
            "target_location": self.target_location,
            "needs_more_steps": self.needs_more_steps,
            "goal_description": self.goal_description,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
        }
        if self.action:
            result["action"] = self.action.to_dict()
        if self.actions:
            result["actions"] = [a.to_dict() for a in self.actions]
        return result


class PlannerService:
    """
    LLM-based planner that decides the agent's next move.
    
    Given user input and page context, outputs:
    - Whether to take an action (scroll, click, etc.)
    - Whether to speak (and what intent)
    - The order of operations
    """
    
    # Phase 1: Create a high-level navigation plan based on site_map
    PLAN_PROMPT = """You are a navigation planner for a web app demo.
Given the user's request and the site structure, create a step-by-step plan.

SITE STRUCTURE:
{site_map}

HOME URL: {home_url}

CURRENT URL: {current_url}

AVAILABLE CLICKABLE ELEMENTS ON THIS PAGE:
{available_elements}

USER REQUEST: "{user_message}"

Create a plan with numbered steps. Each step should be ONE of:
- "navigate: <url>" - Go directly to a URL (ONLY use home_url!)
- "click: <element_text>" - Click a button/link (MUST be in AVAILABLE ELEMENTS!)
- "speak: <message>" - Say something to the user
- "done" - Plan complete

OUTPUT JSON:
{{
    "goal": "What the user wants to achieve",
    "target_section": "The section user wants (or null if just a question)",
    "target_button_found": true | false,
    "plan": [
        {{"step": 1, "action": "speak", "details": "Let me show you!"}},
        {{"step": 2, "action": "click", "details": "Your Journey"}},
        {{"step": 3, "action": "done", "details": null}}
    ],
    "speech_if_no_action": "Response if just a question"
}}

CRITICAL NAVIGATION LOGIC:

1. FIRST, check if the target button is in AVAILABLE ELEMENTS:
   - Look for button_text from SITE STRUCTURE in the available elements
   - Example: User wants "journaling" → look for "Start Today's Reflection"

2. IF target button IS in available elements:
   → Plan: speak, click it, done
   
3. IF target button is NOT in available elements:
   → Plan: speak, navigate to HOME URL, then click the feature button
   → This shows the user the full navigation path!

4. ONLY use "navigate" with the HOME URL - never other URLs!
   All other navigation must be through clicking.

5. IMPORTANT - After navigating to HOME URL:
   - You are ALREADY on the "Your Journey" tab (it's the default view)
   - Do NOT click "Your Journey" - just click the feature button directly!
   - Example: navigate to home → click "Sacred Library" (NOT: click "Your Journey" first)

6. Only click "Your Journey" if:
   - You're currently on "Sister Circle" tab and need to switch
   - The available elements show community posts (Reply, likes, etc.)

EXAMPLE - User on /reflections page asks "show me meditation":
{{
    "goal": "Show the meditation feature",
    "target_section": "meditation",
    "target_button_found": false,
    "plan": [
        {{"step": 1, "action": "speak", "details": "Sure! Let me take you there."}},
        {{"step": 2, "action": "navigate", "details": "{home_url}"}},
        {{"step": 3, "action": "click", "details": "Listen Now"}},
        {{"step": 4, "action": "done", "details": null}}
    ]
}}

Only output valid JSON."""

    # Phase 2: Execute a plan step by finding the right element
    EXECUTE_PROMPT = """You are executing step {step_num} of a navigation plan.

CURRENT PLAN STEP: {plan_step}
TARGET SECTION: {target_section}

CURRENT PAGE:
- URL: {current_url}
- Title: {page_title}

CLICKABLE ELEMENTS ON THIS PAGE:
{clickable_elements}

VISIBLE TEXT ON PAGE:
{page_text}

Find the EXACT element to click from CLICKABLE ELEMENTS that matches the plan step.

OUTPUT JSON:
{{
    "found_element": true | false,
    "element_to_click": "EXACT text from clickable elements (or null if not found)",
    "action_type": "click" | "scroll_up" | "wait" | "none",
    "reasoning": "Why this element matches the plan step",
    "fallback_action": "scroll_up" | "scroll_down" | "click_tab" | "none" (if element not found)
}}

MATCHING RULES:
- For "navigate_to: journaling" → look for "Start Today's Reflection" or "reflection" buttons
- For "navigate_to: meditation" → look for "Listen Now" or "audio" buttons
- For "navigate_to: booklets" → look for "Sacred Library" or "library" buttons
- For "navigate_to: community" → look for "Sister Circle" tab

TAB SWITCHING:
- If you can't find a feature button, look for "Your Journey" tab and click it first
- If you see community posts (Reply, likes) but need features → click "Your Journey" tab

CRITICAL - NEVER USE go_back ON DASHBOARD:
- If URL contains "/dashboard" → NEVER use go_back (it goes to login page!)
- Instead use: scroll_up, or click a tab like "Your Journey"

IMPORTANT: Only use text that EXACTLY appears in CLICKABLE ELEMENTS list!

Only output valid JSON."""

    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-4o-mini"
        self.current_plan = None  # Store active plan
        self.current_plan_step = 0  # Track execution progress
        logger.info("PlannerService initialized")
    
    def _detect_location(self, url: str, title: str = "") -> str:
        """Detect current location from URL and title."""
        url_lower = url.lower()
        title_lower = title.lower()
        
        # Check for signin/login page first
        if '/signin' in url_lower or '/login' in url_lower:
            return "signin"
        
        # Check URL path for location
        if '/reflection' in url_lower or '/journal' in url_lower or '/prompt' in url_lower:
            return "journaling"
        elif '/audio' in url_lower or '/meditation' in url_lower:
            return "meditation"
        elif '/booklet' in url_lower or '/library' in url_lower or '/sacred' in url_lower:
            return "booklets"
        elif '/community' in url_lower or '/circle' in url_lower:
            return "community"
        elif '/dashboard' in url_lower or url_lower.endswith('/dashboard'):
            return "dashboard"
        
        # Check title as fallback
        if 'reflection' in title_lower or 'journal' in title_lower:
            return "journaling"
        elif 'library' in title_lower or 'booklet' in title_lower:
            return "booklets"
        elif 'meditation' in title_lower or 'audio' in title_lower:
            return "meditation"
        elif 'circle' in title_lower or 'community' in title_lower:
            return "community"
        
        return "dashboard"  # Default
    
    async def create_navigation_plan(
        self,
        user_message: str,
        current_url: str,
        page_title: str,
        site_map: list[dict],
        available_elements: list[str] = None,
        home_url: str = ""
    ) -> dict:
        """
        Phase 1: Create a high-level navigation plan.
        
        Uses simple logic:
        - If target button is on current page → click directly
        - If target button is NOT on current page → go to home first, then click through
        
        Returns:
            dict with 'goal', 'plan' (list of steps), 'speech_if_no_action'
        """
        # Format site_map for prompt - show section, description, and button_text
        site_map_str = "\n".join([
            f"- {s['section']}: {s['description']} (button: \"{s.get('button_text', 'N/A')}\")"
            for s in site_map
        ])
        
        # Format available elements
        elements_str = ", ".join([f'"{el}"' for el in (available_elements or [])[:15]])
        if not elements_str:
            elements_str = "(no clickable elements found)"
        
        prompt = self.PLAN_PROMPT.format(
            site_map=site_map_str,
            home_url=home_url,
            current_url=current_url,
            available_elements=elements_str,
            user_message=user_message
        )
        
        logger.info(f"🗺️ Creating navigation plan for: '{user_message}'")
        logger.info(f"📍 Current URL: {current_url}")
        logger.info(f"🏠 Home URL: {home_url}")
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content or "{}")
            
            # Store the plan
            self.current_plan = result
            self.current_plan_step = 0
            
            # Log the plan
            logger.info(f"📋 PLAN CREATED:")
            logger.info(f"   Goal: {result.get('goal', 'unknown')}")
            logger.info(f"   Target: {result.get('target_section')}")
            logger.info(f"   Button found on page: {result.get('target_button_found', 'unknown')}")
            if result.get('plan'):
                for step in result['plan']:
                    logger.info(f"   Step {step.get('step')}: {step.get('action')} → {step.get('details')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to create plan: {e}")
            return {
                "goal": user_message,
                "needs_navigation": False,
                "plan": [],
                "speech_if_no_action": "I'm not sure how to help with that. Could you tell me more?"
            }
    
    async def execute_plan_step(
        self,
        plan_step: dict,
        target_section: str,
        current_url: str,
        page_title: str,
        clickable_elements: list[str],
        page_text: str = ""
    ) -> dict:
        """
        Phase 2: Execute a single step by finding the right element.
        
        Returns:
            dict with 'action_type', 'element_to_click', 'found_element', 'reasoning'
        """
        step_action = plan_step.get('action', '')
        step_details = plan_step.get('details', '')
        
        logger.info(f"🎯 Executing step: {step_action} → {step_details}")
        logger.info(f"   Available elements: {clickable_elements[:5]}...")
        
        # Handle special actions directly
        if step_action == "done":
            return {"action_type": "none", "found_element": True, "reasoning": "Plan complete"}
        
        if step_action == "speak":
            return {"action_type": "speak", "speech": step_details, "found_element": True}
        
        if step_action == "navigate":
            # Direct URL navigation - no need for LLM matching!
            return {"action_type": "navigate", "url": step_details, "found_element": True, "reasoning": f"Navigate directly to {step_details}"}
        
        if step_action == "navigate_to" and step_details == "dashboard":
            # Legacy: Going to dashboard = go back
            return {"action_type": "go_back", "found_element": True, "reasoning": "Go back to reach dashboard"}
        
        # For click/navigate actions, use LLM to find the right element
        clickables_str = "\n".join([f"- \"{el}\"" for el in clickable_elements]) if clickable_elements else "(no elements found)"
        
        prompt = self.EXECUTE_PROMPT.format(
            step_num=plan_step.get('step', 1),
            plan_step=f"{step_action}: {step_details}",
            target_section=target_section or step_details,
            current_url=current_url,
            page_title=page_title,
            clickable_elements=clickables_str,
            page_text=page_text[:500] if page_text else "(no text)"
        )
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content or "{}")
            
            logger.info(f"   Found element: {result.get('found_element')} → '{result.get('element_to_click')}'")
            logger.info(f"   Action: {result.get('action_type')} | Reason: {result.get('reasoning')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to execute step: {e}")
            return {"action_type": "none", "found_element": False, "reasoning": f"Error: {e}"}
    
    def get_next_plan_step(self) -> Optional[dict]:
        """Get the next step from the current plan."""
        if not self.current_plan or not self.current_plan.get('plan'):
            return None
        
        plan_steps = self.current_plan['plan']
        if self.current_plan_step >= len(plan_steps):
            return None
        
        step = plan_steps[self.current_plan_step]
        self.current_plan_step += 1
        return step
    
    def reset_plan(self):
        """Reset the current plan."""
        self.current_plan = None
        self.current_plan_step = 0
    
    async def plan(
        self,
        user_message: str,
        page_state: Optional[dict] = None,
        available_actions: Optional[list[str]] = None,
        demo_stage: str = "exploring",
        conversation_summary: Optional[str] = None,
        site_map: Optional[list[dict]] = None,
    ) -> Plan:
        """
        Generate a plan based on user input and context.
        
        Args:
            user_message: What the user said
            page_state: Current page context from Perception
            available_actions: List of clickable elements on the page
            demo_stage: Current demo stage (intro, exploring, deep_dive, closing)
            conversation_summary: Brief summary of conversation so far
            site_map: Site navigation structure for intent-based navigation
            
        Returns:
            Plan object with decision, action, and speech intent
        """
        logger.info(f"📋 Planning for: '{user_message}'")
        logger.debug(f"Demo stage: {demo_stage}")
        
        # Check if user wants to navigate to a known section
        matched_section = match_site_section(user_message, site_map or [])
        if matched_section:
            logger.info(f"🗺️ Matched site section: {matched_section.get('section')}")
            logger.debug(f"Target intent: {matched_section.get('target_intent')}")
        
        # Build context for LLM
        context_parts = []
        
        # Determine current location from URL/title
        current_url = page_state.get('url', '') if page_state else ''
        current_title = page_state.get('title', '') if page_state else ''
        
        # Smart location detection
        detected_location = "dashboard"  # Default to dashboard
        url_lower = current_url.lower()
        title_lower = current_title.lower()
        
        # Check URL path for location - most reliable
        if '/reflection' in url_lower or '/journal' in url_lower or '/prompt' in url_lower:
            detected_location = "journaling"
        elif '/audio' in url_lower or '/meditation' in url_lower:
            detected_location = "meditation"
        elif '/booklet' in url_lower or '/library' in url_lower or '/sacred' in url_lower:
            detected_location = "booklets"
        elif '/community' in url_lower or '/circle' in url_lower:
            detected_location = "community"
        # Check title as fallback
        elif 'reflection' in title_lower or 'journal' in title_lower:
            detected_location = "journaling"
        elif 'library' in title_lower or 'booklet' in title_lower:
            detected_location = "booklets"
        elif 'meditation' in title_lower or 'audio' in title_lower:
            detected_location = "meditation"
        elif 'circle' in title_lower or 'community' in title_lower:
            detected_location = "community"
        # Default: if at root or has healing/journey in title, it's dashboard
        elif current_url.endswith('/') or '/dashboard' in url_lower:
            detected_location = "dashboard"
        
        logger.info(f"📍 Detected location: {detected_location} (from URL: {current_url})")
        
        # Page context
        if page_state:
            context_parts.append(f"CURRENT PAGE:")
            context_parts.append(f"  URL: {current_url}")
            context_parts.append(f"  Title: {current_title}")
            context_parts.append(f"  ⚡ DETECTED LOCATION: {detected_location}")
            
            # Page text content - what's actually visible on screen
            text_content = page_state.get("text_content", "")
            if text_content:
                # Truncate to first 800 chars for context
                truncated = text_content[:800].strip()
                context_parts.append(f"\nVISIBLE TEXT ON SCREEN:")
                context_parts.append(f"  {truncated}")
                if len(text_content) > 800:
                    context_parts.append("  [... more text below ...]")
            
            # Visible sections
            sections = page_state.get("sections", [])
            if sections:
                context_parts.append(f"  Visible sections: {[s.get('heading', '') for s in sections[:5]]}")
            
            logger.debug(f"Page: {current_title}")
        
        # Available actions - CRITICAL for LLM to pick correct button
        if available_actions:
            context_parts.append(f"\nCLICKABLE ELEMENTS ON PAGE (pick from these for clicks!):")
            for i, action in enumerate(available_actions[:20]):
                context_parts.append(f"  {i+1}. \"{action}\"")
            logger.debug(f"Available actions: {len(available_actions)} elements")
        else:
            context_parts.append("\nCLICKABLE ELEMENTS ON PAGE:")
            context_parts.append("  (none detected - scroll may be needed)")
            context_parts.append("  Available: scroll up, scroll down")
        
        # Site map - for understanding what sections exist (NOT for click targets!)
        if site_map:
            context_parts.append(f"\nSITE SECTIONS (for context, NOT click targets):")
            for section in site_map:
                context_parts.append(f"  - {section.get('section')}: {section.get('description', '')}")
        
        # If we matched a section, tell the LLM - but DON'T tell it what to click!
        # The LLM must pick from CLICKABLE ELEMENTS above
        if matched_section:
            context_parts.append(f"\n⚡ USER WANTS TO GO TO: {matched_section.get('section')}")
            context_parts.append(f"   Look for a button in CLICKABLE ELEMENTS that leads there")
        
        # Demo stage
        context_parts.append(f"\nDEMO STAGE: {demo_stage}")
        
        # Conversation summary
        if conversation_summary:
            context_parts.append(f"\nCONVERSATION SO FAR: {conversation_summary}")
        
        context = "\n".join(context_parts)
        
        # Build messages
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"CONTEXT:\n{context}\n\nUSER SAID: \"{user_message}\""}
        ]
        
        logger.debug("Calling LLM for planning decision...")
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=500,  # More tokens for multi-step plans
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content or "{}"
            logger.debug(f"Raw LLM response: {result_text}")
            
            # Parse JSON response
            result = json.loads(result_text)
            
            # Extract thinking context
            thinking = result.get("thinking", {})
            current_loc = thinking.get("current_location", "unknown")
            target_loc = thinking.get("target_section", "") or thinking.get("goal", "")
            
            logger.info(f"📍 Location: {current_loc} → Target: {target_loc or 'none'}")
            
            # Parse single action (new format) or actions array (old format)
            action = None
            actions = []
            
            # New format: single action
            action_data = result.get("action")
            if action_data and isinstance(action_data, dict):
                action = BrowserAction(
                    action_type=action_data.get("action_type", "none"),
                    target=action_data.get("target"),
                    description=action_data.get("reason", "")
                )
                actions = [action]
                logger.info(f"🎯 Action: {action.action_type} → {action.target}")
            
            # Fallback: old format with actions array
            elif result.get("actions"):
                actions_data = result.get("actions", [])
                for act_data in actions_data:
                    act = BrowserAction(
                        action_type=act_data.get("action_type", "none"),
                        target=act_data.get("target"),
                        description=act_data.get("reason", "")
                    )
                    actions.append(act)
                    logger.info(f"🎯 Action: {act.action_type} → {act.target}")
                action = actions[0] if actions else None
            
            # Get speech (actual text to say)
            speech = result.get("speech", "")
            
            # Parse step-by-step flags
            needs_more_steps = result.get("needs_more_steps", False)
            goal_description = thinking.get("goal", "")
            
            plan = Plan(
                decision=result.get("decision", "speak_only"),
                action=action,
                actions=actions,
                speech=speech,
                speech_intent=speech,  # Use speech as intent for backwards compat
                current_location=current_loc,
                target_location=target_loc or "",
                needs_more_steps=needs_more_steps,
                goal_description=goal_description,
                reasoning=result.get("reasoning", ""),
                confidence=result.get("confidence", 0.5)
            )
            
            more_steps_str = " [MORE STEPS NEEDED]" if needs_more_steps else ""
            logger.info(f"✓ Plan: {plan.decision} ({len(actions)} action){more_steps_str}")
            logger.debug(f"Reasoning: {plan.reasoning}")
            logger.debug(f"Speech: {plan.speech[:50]}..." if plan.speech else "No speech")
            
            return plan
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return self._fallback_plan(user_message)
        except Exception as e:
            logger.error(f"Planning error: {e}")
            return self._fallback_plan(user_message)
    
    def _fallback_plan(self, user_message: str) -> Plan:
        """
        Fallback plan when LLM fails - use simple rules.
        """
        logger.warning("Using fallback rule-based planning")
        
        lower = user_message.lower()
        
        # Check for action keywords
        if any(kw in lower for kw in ["scroll down", "go down", "show more", "next"]):
            return Plan(
                decision="speak_then_action",
                action=BrowserAction("scroll", "down", "Scrolling down"),
                speech_intent="acknowledge",
                reasoning="User requested scroll down",
                confidence=0.8
            )
        
        if any(kw in lower for kw in ["scroll up", "go up", "back up", "previous"]):
            return Plan(
                decision="speak_then_action",
                action=BrowserAction("scroll", "up", "Scrolling up"),
                speech_intent="acknowledge",
                reasoning="User requested scroll up",
                confidence=0.8
            )
        
        if any(kw in lower for kw in ["show me", "let me see", "can you show"]):
            return Plan(
                decision="action_then_speak",
                action=BrowserAction("scroll", "down", "Looking for that section"),
                speech_intent="describe_feature",
                reasoning="User wants to see something",
                confidence=0.6
            )
        
        # Default: just speak
        return Plan(
            decision="speak_only",
            action=None,
            speech_intent="answer_question",
            reasoning="Fallback: treating as conversational",
            confidence=0.5
        )
    
    async def quick_check(self, user_message: str) -> bool:
        """
        Quick rule-based check: does this message likely need an action?
        Use this for fast filtering before calling the full LLM planner.
        
        Returns True if action is likely needed.
        """
        lower = user_message.lower()
        
        action_keywords = [
            "scroll", "show", "click", "go to", "take me", "navigate",
            "next", "previous", "more", "demo", "see", "look at",
            "open", "close", "expand", "collapse"
        ]
        
        needs_action = any(kw in lower for kw in action_keywords)
        
        logger.debug(f"Quick check: '{user_message[:30]}...' → action_likely={needs_action}")
        
        return needs_action


# Singleton instance
_planner: Optional[PlannerService] = None


def get_planner() -> PlannerService:
    """Get the singleton planner instance."""
    global _planner
    if _planner is None:
        _planner = PlannerService()
    return _planner

