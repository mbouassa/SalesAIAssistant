"""
Demo Runner Service - Executes scripted demo playbooks.

Handles:
- Loading playbook YAML files
- Executing step sequences
- Validating success conditions
- Milestone narration
- Barge-in interruption
- Retry/fallback logic
"""

import asyncio
import logging
import yaml
from pathlib import Path
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

from app.services.browser_service import BrowserSession

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [DemoRunner] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class DemoState(Enum):
    """Current state of demo execution."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class PlaybookStep:
    """A single step in a demo playbook."""
    id: str
    action: dict
    narrate: str = ""
    success: Optional[dict] = None
    fallbacks: list = field(default_factory=list)


@dataclass
class Playbook:
    """A complete demo playbook."""
    company_id: str
    name: str
    description: str
    start_url: str
    triggers: list[str]
    steps: list[PlaybookStep]
    fallback_narration: dict = field(default_factory=dict)
    
    @classmethod
    def from_yaml(cls, path: Path) -> "Playbook":
        """Load playbook from YAML file."""
        logger.debug(f"Loading playbook from: {path}")
        
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        meta = data.get("meta", {})
        
        # Parse steps
        steps = []
        for step_data in data.get("steps", []):
            action = step_data.get("action", {})
            
            # Handle fallbacks - they can be in the action or at step level
            fallbacks = action.pop("fallbacks", []) if isinstance(action, dict) else []
            
            step = PlaybookStep(
                id=step_data.get("id", "unknown"),
                action=action,
                narrate=step_data.get("narrate", ""),
                success=step_data.get("success"),
                fallbacks=fallbacks
            )
            steps.append(step)
        
        playbook = cls(
            company_id=meta.get("company_id", ""),
            name=meta.get("name", "Demo"),
            description=meta.get("description", ""),
            start_url=meta.get("start_url", ""),
            triggers=data.get("triggers", []),
            steps=steps,
            fallback_narration=data.get("fallback_narration", {})
        )
        
        logger.info(f"✓ Loaded playbook: {playbook.name} ({len(playbook.steps)} steps)")
        return playbook


class DemoRunner:
    """
    Executes demo playbooks step by step.
    
    Features:
    - Step-by-step execution with validation
    - Milestone narration (speaks at key points)
    - Barge-in support (can be interrupted mid-demo)
    - Retry with fallback selectors
    - State tracking for UI/debugging
    """
    
    def __init__(
        self,
        browser_session: BrowserSession,
        speak_callback: Callable[[str], Awaitable[None]],
        check_interrupted: Callable[[], bool],
    ):
        """
        Initialize the demo runner.
        
        Args:
            browser_session: Active Browserbase session for browser control
            speak_callback: Async function to speak text (calls TTS)
            check_interrupted: Function that returns True if user interrupted
        """
        self.browser = browser_session
        self.speak = speak_callback
        self.check_interrupted = check_interrupted
        
        self.state = DemoState.IDLE
        self.current_playbook: Optional[Playbook] = None
        self.current_step_index = 0
        self.steps_completed = 0
        
        logger.info("DemoRunner initialized")
    
    async def run_playbook(self, playbook: Playbook) -> bool:
        """
        Execute a complete playbook.
        
        Args:
            playbook: The playbook to execute
            
        Returns:
            True if completed successfully, False if interrupted/failed
        """
        logger.info(f"🎬 Starting playbook: {playbook.name}")
        
        self.current_playbook = playbook
        self.current_step_index = 0
        self.steps_completed = 0
        self.state = DemoState.RUNNING
        
        try:
            for i, step in enumerate(playbook.steps):
                self.current_step_index = i
                
                # Check for interruption before each step
                if self.check_interrupted():
                    logger.info("🛑 Demo interrupted by user")
                    self.state = DemoState.INTERRUPTED
                    
                    # Speak interruption message
                    interrupt_msg = playbook.fallback_narration.get(
                        "demo_interrupted", 
                        "Got it — I'll pause the demo. What would you like to focus on?"
                    )
                    await self.speak(interrupt_msg)
                    return False
                
                # Execute the step
                success = await self._execute_step(step)
                
                if not success:
                    logger.warning(f"Step '{step.id}' failed, continuing anyway")
                    # Speak failure message but continue
                    fail_msg = playbook.fallback_narration.get(
                        "action_failed",
                        "Let me try something else."
                    )
                    await self.speak(fail_msg)
                
                self.steps_completed += 1
                
                # Small pause between steps for natural pacing
                await asyncio.sleep(0.5)
            
            self.state = DemoState.COMPLETED
            logger.info(f"✓ Playbook completed: {self.steps_completed}/{len(playbook.steps)} steps")
            return True
            
        except Exception as e:
            logger.error(f"Playbook execution error: {e}")
            self.state = DemoState.FAILED
            return False
    
    async def _execute_step(self, step: PlaybookStep) -> bool:
        """Execute a single playbook step."""
        logger.info(f"📍 Step: {step.id}")
        
        action = step.action
        action_type = action.get("type", "wait")
        
        # Execute the action
        action_success = await self._perform_action(action_type, action, step.fallbacks)
        
        # Narrate if there's narration for this step
        if step.narrate:
            logger.debug(f"Narrating: {step.narrate[:50]}...")
            await self.speak(step.narrate)
        
        # Validate success condition if specified
        if step.success:
            validation_success = await self._validate_success(step.success)
            if not validation_success:
                logger.warning(f"Success validation failed for step '{step.id}'")
                return False
        
        return action_success
    
    async def _perform_action(
        self, 
        action_type: str, 
        action: dict,
        fallbacks: list
    ) -> bool:
        """Perform a browser action with fallback support."""
        
        if action_type == "wait":
            duration = action.get("duration", 1)
            logger.debug(f"Waiting {duration}s")
            await asyncio.sleep(duration)
            return True
        
        elif action_type == "scroll":
            direction = action.get("target", "down")
            logger.debug(f"Scrolling {direction}")
            await self.browser.scroll(direction)
            return True
        
        elif action_type == "click":
            target = action.get("target", "")
            intent = action.get("intent", "")
            
            # If we have an intent, use LLM to find the best match first
            if intent:
                logger.debug(f"Using intent-based matching: '{intent}'")
                best_match = await self._find_best_element(intent)
                if best_match:
                    logger.debug(f"Intent matched to: '{best_match}'")
                    if await self._try_click_direct(best_match):
                        return True
            
            # Try primary target
            if await self._try_click_direct(target):
                return True
            
            # Try fallbacks
            for fallback in fallbacks:
                logger.debug(f"Trying fallback: {fallback}")
                if await self._try_click_direct(fallback):
                    return True
            
            logger.warning(f"Click failed for '{target}' and all fallbacks")
            return False
        
        elif action_type == "navigate":
            url = action.get("target", "")
            if url:
                logger.debug(f"Navigating to: {url}")
                await self.browser.navigate(url)
                await asyncio.sleep(1)  # Wait for page load
                return True
            return False
        
        elif action_type == "go_back":
            logger.debug("Going back in browser history")
            try:
                await self.browser.page.go_back()
                await asyncio.sleep(1)  # Wait for page load
                return True
            except Exception as e:
                logger.warning(f"Go back failed: {e}")
                return False
        
        else:
            logger.warning(f"Unknown action type: {action_type}")
            return True  # Don't fail on unknown actions
    
    async def _try_click_direct(self, target: str) -> bool:
        """Try to click an element by exact text match."""
        if not target:
            return False
        
        # Try different selector strategies
        selectors = [
            f"button:has-text('{target}')",
            f"a:has-text('{target}')",
            f"[role='button']:has-text('{target}')",
            f"[role='tab']:has-text('{target}')",
            f"div:has-text('{target}')",
            f"text='{target}'",
        ]
        
        for selector in selectors:
            try:
                success = await self.browser.click(selector)
                if success:
                    logger.debug(f"✓ Clicked: {target}")
                    await asyncio.sleep(0.5)  # Wait for UI to respond
                    return True
            except Exception as e:
                continue
        
        return False
    
    async def _try_click(self, target: str) -> bool:
        """Try to click an element, using LLM fallback if needed."""
        if not target:
            return False
        
        # First try direct match
        if await self._try_click_direct(target):
            return True
        
        # If that fails, try LLM-based matching
        logger.debug(f"Direct click failed for '{target}', trying LLM match...")
        best_match = await self._find_best_element(target)
        
        if best_match and best_match != target:
            logger.debug(f"LLM matched '{target}' → '{best_match}'")
            return await self._try_click_direct(best_match)
        
        return False
    
    async def _find_best_element(self, intent: str) -> Optional[str]:
        """
        Use LLM to find the best matching element for an intent.
        
        Args:
            intent: What we want to click (e.g., "the journaling feature")
            
        Returns:
            The actual button/link text to click, or None if no match
        """
        try:
            # Get available elements from the page
            page_content = await self.browser.get_page_content()
            clickables = page_content.get("clickable_elements", [])
            
            if not clickables:
                return None
            
            # Extract text from clickable elements
            available = []
            for el in clickables:
                text = el.get("text", "").strip()
                if text and len(text) < 100:  # Skip very long text
                    available.append(text)
            
            if not available:
                return None
            
            # Ask LLM to find the best match
            from openai import AsyncOpenAI
            from app.core.config import get_settings
            settings = get_settings()
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            
            prompt = f"""Given these clickable elements on a webpage:
{available}

Which one best matches this intent: "{intent}"

Rules:
- Return ONLY the exact text of the matching element
- If no good match, return "NONE"
- Pick the most relevant button/link for the intent

Answer with just the element text:"""

            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0
            )
            
            answer = response.choices[0].message.content.strip()
            
            if answer.upper() == "NONE" or answer not in available:
                # Try partial match
                for el in available:
                    if answer.lower() in el.lower() or el.lower() in answer.lower():
                        return el
                return None
            
            return answer
            
        except Exception as e:
            logger.warning(f"Error finding element match: {e}")
            return None
    
    async def _validate_success(self, success_condition: dict) -> bool:
        """Validate that a step succeeded."""
        condition_type = success_condition.get("type", "")
        value = success_condition.get("value", "")
        
        if condition_type == "url_contains":
            try:
                page_content = await self.browser.get_page_content()
                current_url = page_content.get("url", "")
                return value in current_url
            except:
                return False
        
        elif condition_type == "element_visible":
            # For now, just check if page content contains the text
            try:
                page_content = await self.browser.get_page_content()
                page_text = str(page_content).lower()
                return value.lower() in page_text
            except:
                return False
        
        # Unknown condition type - pass
        return True
    
    def interrupt(self) -> None:
        """Interrupt the current demo."""
        if self.state == DemoState.RUNNING:
            logger.info("Demo interrupt requested")
            self.state = DemoState.INTERRUPTED
    
    def get_progress(self) -> dict:
        """Get current demo progress."""
        total = len(self.current_playbook.steps) if self.current_playbook else 0
        return {
            "state": self.state.value,
            "current_step": self.current_step_index,
            "steps_completed": self.steps_completed,
            "total_steps": total,
            "playbook_name": self.current_playbook.name if self.current_playbook else None,
        }


# Playbook loader utility
_playbooks_cache: dict[str, Playbook] = {}


def load_playbook(company_id: str) -> Optional[Playbook]:
    """Load a playbook for a company."""
    if company_id in _playbooks_cache:
        return _playbooks_cache[company_id]
    
    # Look for playbook file
    playbooks_dir = Path(__file__).parent.parent / "playbooks"
    
    # Try different naming conventions
    base_name = company_id.replace('persona_', '')
    possible_names = [
        f"{company_id}.yaml",           # persona_healingpath.yaml
        f"{base_name}.yaml",            # healingpath.yaml
        f"healing_path.yaml",           # healing_path.yaml (special case)
        f"{base_name.replace('healing', 'healing_')}.yaml",  # healing_path.yaml
    ]
    
    logger.debug(f"Looking for playbook: {possible_names}")
    
    for name in possible_names:
        playbook_path = playbooks_dir / name
        if playbook_path.exists():
            playbook = Playbook.from_yaml(playbook_path)
            _playbooks_cache[company_id] = playbook
            return playbook
    
    # Also try listing all playbooks and matching by company_id in meta
    try:
        for yaml_file in playbooks_dir.glob("*.yaml"):
            if yaml_file.name == "__init__.py":
                continue
            playbook = Playbook.from_yaml(yaml_file)
            if playbook.company_id == company_id:
                _playbooks_cache[company_id] = playbook
                return playbook
    except Exception as e:
        logger.warning(f"Error scanning playbooks: {e}")
    
    logger.warning(f"No playbook found for company: {company_id}")
    return None


async def is_demo_request(user_message: str, client) -> bool:
    """
    Use LLM to determine if user is asking for a full demo.
    
    Args:
        user_message: What the user said
        client: OpenAI async client
        
    Returns:
        True if user wants a full demo walkthrough
    """
    prompt = """Determine if the user is asking for a full product demo or walkthrough.

Return "YES" if they want a complete guided tour/demo of the product.
Return "NO" if they're asking a specific question or want something else.

Examples of YES:
- "Give me a demo"
- "Show me everything"
- "Walk me through the product"
- "Can you do a full tour?"
- "Demo please"
- "Show me how it all works"

Examples of NO:
- "What is this?"
- "How much does it cost?"
- "Scroll down"
- "Click on pricing"
- "Tell me about the features"

User said: "{message}"

Answer with only YES or NO:"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt.format(message=user_message)}],
            max_tokens=5,
            temperature=0
        )
        
        answer = response.choices[0].message.content.strip().upper()
        is_demo = answer == "YES"
        
        logger.debug(f"Demo request check: '{user_message}' → {answer}")
        return is_demo
        
    except Exception as e:
        logger.error(f"Error checking demo request: {e}")
        return False


def matches_trigger(user_message: str, playbook: Playbook) -> bool:
    """
    Quick check if user message matches any playbook trigger.
    This is a fast pre-filter before the LLM check.
    """
    lower_message = user_message.lower().strip()
    
    # Quick keyword check
    demo_keywords = ["demo", "tour", "walk me through", "show me everything", "walkthrough"]
    
    for keyword in demo_keywords:
        if keyword in lower_message:
            logger.debug(f"Demo keyword matched: '{keyword}'")
            return True
    
    return False

