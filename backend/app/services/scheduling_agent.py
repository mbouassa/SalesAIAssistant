"""
Scheduling Agent - VLM-based goal-oriented agent for booking calls.

Uses Vision Language Model (GPT-4o) with screenshots to navigate any scheduling page
(Calendly, Cal.com, etc.) without hardcoded selectors or step sequences.

The agent sees the screen visually and decides actions based on what it sees,
just like a human would.

Uses LLM-powered element finding for robust clicking of icons, arrows, and complex elements.
"""

import json
import asyncio
import base64
import re
from typing import Optional, Callable, Awaitable
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.browser_service import BrowserSession
from app.services.scheduling_tools import (
    SCHEDULING_TOOLS,
    get_vlm_system_prompt,
    get_info_extraction_prompt
)


class SchedulingAgent:
    """
    VLM-based goal-oriented agent for scheduling calls.
    
    This agent:
    1. Takes screenshots of the scheduling page
    2. Sends screenshots to VLM (GPT-4o)
    3. VLM decides what action to take based on what it SEES
    4. Executes action and repeats
    
    No hardcoded selectors or state tracking - pure visual understanding.
    """
    
    def __init__(
        self,
        browser_session: BrowserSession,
        speak_callback: Callable[[str], Awaitable[None]],
        config: dict
    ):
        """
        Initialize the scheduling agent.
        
        Args:
            browser_session: Active browser session for interactions
            speak_callback: Async function to speak to user
            config: Scheduling config from persona (goal, url, founder_name)
        """
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-4o"  # VLM with vision capabilities
        
        self.browser = browser_session
        self.speak = speak_callback
        
        # Config from persona
        self.base_goal = config.get('goal', 'Schedule a call')
        self.scheduling_url = config.get('url', config.get('calendly_url', ''))
        self.founder_name = config.get('founder_name', 'the team')
        
        # State
        self.is_active = False
        self.goal_complete = False
        self.interrupted = False  # Set by AI Agent when user speaks mid-loop
        
        # Collected information (used to build dynamic goal)
        self.collected_info = {
            'date': None,
            'time': None,
            'name': None,
            'email': None
        }
        
        # Auto-continue settings
        self.MAX_AUTO_CONTINUE = 10  # Higher limit since VLM is smarter
        
        print(f"[SchedulingAgent] 🎯 VLM-based agent initialized", flush=True)
        print(f"[SchedulingAgent]   Base goal: {self.base_goal}", flush=True)
        print(f"[SchedulingAgent]   URL: {self.scheduling_url}", flush=True)
        print(f"[SchedulingAgent]   Founder: {self.founder_name}", flush=True)
    
    def _build_goal_string(self) -> str:
        """
        Build dynamic goal string from collected information.
        
        This is the key to the goal-oriented approach - the goal evolves
        as we learn more about what the user wants.
        """
        goal_parts = [self.base_goal, f"with {self.founder_name}"]
        
        if self.collected_info['date']:
            goal_parts.append(f"for {self.collected_info['date']}")
        
        if self.collected_info['time']:
            goal_parts.append(f"at {self.collected_info['time']}")
        
        if self.collected_info['name'] or self.collected_info['email']:
            user_parts = []
            if self.collected_info['name']:
                user_parts.append(self.collected_info['name'])
            if self.collected_info['email']:
                user_parts.append(f"({self.collected_info['email']})")
            goal_parts.append(f"User: {' '.join(user_parts)}")
        
        return " ".join(goal_parts)
    
    async def start(self) -> None:
        """
        Start the scheduling flow by navigating to the scheduling URL.
        """
        print(f"\n{'='*60}", flush=True)
        print(f"[SchedulingAgent] 🚀 STARTING VLM SCHEDULING FLOW", flush=True)
        print(f"{'='*60}", flush=True)
        
        if not self.scheduling_url:
            print(f"[SchedulingAgent] ❌ No scheduling URL configured!", flush=True)
            await self.speak("I'm sorry, I don't have a scheduling link set up. Please contact us directly!")
            return
        
        # Navigate to scheduling page
        print(f"[SchedulingAgent] 🌐 Navigating to: {self.scheduling_url}", flush=True)
        await self.speak("I'm opening up the calendar now. Take a look and let me know what time works best for you!")
        
        if self.browser:
            success = await self.browser.navigate(self.scheduling_url)
            if success:
                print(f"[SchedulingAgent] ✅ Navigated to scheduling page", flush=True)
                self.is_active = True
                await asyncio.sleep(1.5)  # Wait for page to fully load
            else:
                print(f"[SchedulingAgent] ❌ Failed to navigate", flush=True)
                await self.speak("I'm having trouble opening the calendar. Let me try again.")
        else:
            print(f"[SchedulingAgent] ❌ No browser session!", flush=True)
    
    async def process_turn(self, user_message: str) -> None:
        """
        Process a user message during the scheduling flow.
        
        This is the VLM agent loop:
        1. Extract info from user message → update goal
        2. LOOP:
           - Take screenshot
           - Send to VLM with goal
           - VLM decides action based on what it SEES
           - Execute action
           - VLM decides if it needs to continue
        3. Speak response
        """
        print(f"\n{'='*60}", flush=True)
        print(f"[SchedulingAgent] 📥 PROCESSING TURN (VLM MODE)", flush=True)
        print(f"[SchedulingAgent] User said: '{user_message}'", flush=True)
        print(f"{'='*60}", flush=True)
        
        # Reset interruption flag for new turn
        self.interrupted = False
        
        # Step 1: Extract any new info from user message
        print(f"\n[SchedulingAgent] 🔍 STEP 1: Extracting info from message...", flush=True)
        await self._extract_info_from_message(user_message)
        
        # Build overarching goal (big picture)
        overarching_goal = self._build_goal_string()
        print(f"[SchedulingAgent] 🎯 Overarching goal: {overarching_goal}", flush=True)
        print(f"[SchedulingAgent] 💬 Immediate request: {user_message}", flush=True)
        
        # Step 2: VLM agent loop
        loop_count = 0
        final_speech = None
        last_action = None  # Track last action to avoid repeating
        
        while loop_count < self.MAX_AUTO_CONTINUE:
            # Check for user interruption before each iteration
            if self.interrupted:
                print(f"[SchedulingAgent] 🛑 User interrupted - breaking out of VLM loop", flush=True)
                break
            
            loop_count += 1
            print(f"\n[SchedulingAgent] 🔄 VLM LOOP iteration {loop_count}/{self.MAX_AUTO_CONTINUE}", flush=True)
            
            # Take screenshot
            print(f"[SchedulingAgent] 📸 Taking screenshot...", flush=True)
            screenshot = await self._take_screenshot()
            
            if not screenshot:
                print(f"[SchedulingAgent] ❌ Failed to take screenshot", flush=True)
                break
            
            # Call VLM with screenshot (two-tier goals)
            print(f"[SchedulingAgent] 🤖 Sending screenshot to VLM...", flush=True)
            tool_call, speech, should_continue = await self._call_vlm_with_screenshot(
                screenshot, 
                overarching_goal,  # Big picture: "Schedule call with X for date/time"
                user_message,       # Immediate: "My name is Jake and email is..."
                loop_count,
                last_action         # What we just did (to avoid repeating)
            )
            
            if tool_call:
                print(f"[SchedulingAgent] 🛠️ VLM chose tool: {tool_call['name']}", flush=True)
                print(f"[SchedulingAgent] 📦 Arguments: {tool_call['arguments']}", flush=True)
            else:
                print(f"[SchedulingAgent] 💬 VLM chose no tool", flush=True)
            
            if speech:
                print(f"[SchedulingAgent] 🗣️ VLM speech: '{speech[:100]}{'...' if len(speech) > 100 else ''}'", flush=True)
                final_speech = speech
            
            # Execute the tool
            if tool_call:
                print(f"\n[SchedulingAgent] ⚡ Executing tool...", flush=True)
                await self._execute_tool(tool_call)
                # Track last action for context in next iteration
                last_action = f"{tool_call['name']}({tool_call['arguments']})"
            
            # Check if VLM wants to continue
            print(f"[SchedulingAgent] 🔍 VLM says continue? {should_continue}", flush=True)
            
            if not should_continue:
                print(f"[SchedulingAgent] ⏹️ VLM decided to stop - waiting for user", flush=True)
                break
            
            print(f"[SchedulingAgent] ➡️ VLM continuing to next action...", flush=True)
            await asyncio.sleep(0.8)  # Wait for page to update
        
        # Step 3: Sanitize and speak the final response (but NOT if user interrupted)
        if final_speech and not self.interrupted:
            # Clean up any JSON or verbose output before speaking
            clean_speech = await self._sanitize_speech(final_speech)
            print(f"\n[SchedulingAgent] 🔊 Speaking: '{clean_speech}'", flush=True)
            await self.speak(clean_speech)
        elif self.interrupted:
            print(f"\n[SchedulingAgent] 🛑 Skipping speech - user interrupted", flush=True)
        
        print(f"\n[SchedulingAgent] ✅ Turn complete. is_active={self.is_active}, goal_complete={self.goal_complete}", flush=True)
    
    async def _take_screenshot(self) -> Optional[str]:
        """
        Take a screenshot and return as base64 string.
        """
        if not self.browser:
            return None
        
        try:
            screenshot_bytes = await self.browser.take_screenshot()
            if screenshot_bytes:
                base64_image = base64.b64encode(screenshot_bytes).decode('utf-8')
                print(f"[SchedulingAgent] 📸 Screenshot encoded ({len(base64_image)} chars)", flush=True)
                return base64_image
            return None
        except Exception as e:
            print(f"[SchedulingAgent] ❌ Screenshot error: {e}", flush=True)
            return None
    
    async def _call_vlm_with_screenshot(
        self,
        screenshot_base64: str,
        overarching_goal: str,
        user_message: str,
        loop_iteration: int,
        last_action: Optional[str] = None
    ) -> tuple[Optional[dict], Optional[str], bool]:
        """
        Call VLM with screenshot and get the decision.
        
        Args:
            screenshot_base64: Base64 encoded screenshot
            overarching_goal: The big picture goal (schedule call with X for date/time)
            user_message: What the user just said (immediate request)
            loop_iteration: Which iteration of the agent loop we're on
            last_action: What action was just taken (to avoid repeating)
        
        Returns:
            Tuple of (tool_call dict or None, speech text or None, should_continue bool)
        """
        # Build system prompt
        system_prompt = get_vlm_system_prompt(founder_name=self.founder_name)
        
        # Build user message with two-tier goals
        iteration_context = ""
        if loop_iteration > 1:
            iteration_context = f"\n\n[This is action {loop_iteration}. If you've completed the immediate request, stop and wait for user.]"
        
        # Add last action context to avoid repeating
        last_action_context = ""
        if last_action:
            last_action_context = f"\n\nLAST ACTION YOU TOOK: {last_action}\nDo NOT repeat this action. Move to the next step."
        
        user_prompt = f"""Look at this screenshot of a scheduling page.

OVERARCHING GOAL: {overarching_goal}

IMMEDIATE REQUEST: "{user_message}"

KNOWN INFO:
- Date: {self.collected_info['date'] or 'Not yet specified'}
- Time: {self.collected_info['time'] or 'Not yet specified'}
- Name: {self.collected_info['name'] or 'Not yet specified'}
- Email: {self.collected_info['email'] or 'Not yet specified'}

Focus on fulfilling the IMMEDIATE REQUEST. Take ONE action.{last_action_context}{iteration_context}"""

        print(f"\n[SchedulingAgent] 📤 VLM REQUEST:", flush=True)
        print(f"[SchedulingAgent]   Overarching: {overarching_goal}", flush=True)
        print(f"[SchedulingAgent]   Immediate: {user_message}", flush=True)
        print(f"[SchedulingAgent]   Iteration: {loop_iteration}", flush=True)
        if last_action:
            print(f"[SchedulingAgent]   Last action: {last_action}", flush=True)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_base64}",
                                    "detail": "high"  # High detail for reading calendar
                                }
                            }
                        ]
                    }
                ],
                tools=SCHEDULING_TOOLS,
                tool_choice="auto",
                max_tokens=500,
                temperature=0.2  # Low temp for consistency
            )
            
            message = response.choices[0].message
            
            # Extract tool call if present
            tool_call = None
            if message.tool_calls:
                tc = message.tool_calls[0]
                tool_call = {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                }
            
            # Extract speech (content)
            speech = message.content
            
            # FALLBACK: Sometimes VLM writes tool call as JSON in text instead of using tool_calls
            # Parse it from the content if no tool_call was made
            if not tool_call and speech:
                fallback_tool = self._parse_tool_from_text(speech)
                if fallback_tool:
                    print(f"[SchedulingAgent] 🔧 Parsed tool from text (fallback): {fallback_tool}", flush=True)
                    tool_call = fallback_tool
                    # Clean the JSON from the speech
                    speech = self._clean_json_from_speech(speech)
            
            # Determine if VLM wants to continue
            # - Stop if ask_user or done
            # - Stop if no tool called
            # - Continue if action tool called (click, type, go_back)
            # - Scroll is a "single action" - always stop after scroll to wait for user guidance
            should_continue = False
            if tool_call:
                tool_name = tool_call['name']
                if tool_name in ['click', 'type_text', 'go_back']:
                    should_continue = True
                elif tool_name == 'scroll':
                    # Scroll is "dumb" - do once then wait for user
                    should_continue = False
                elif tool_name in ['ask_user', 'done']:
                    should_continue = False
            
            print(f"\n[SchedulingAgent] 📥 VLM RESPONSE:", flush=True)
            print(f"[SchedulingAgent]   Tool: {tool_call}", flush=True)
            print(f"[SchedulingAgent]   Speech: {speech}", flush=True)
            print(f"[SchedulingAgent]   Continue: {should_continue}", flush=True)
            
            return tool_call, speech, should_continue
            
        except Exception as e:
            print(f"[SchedulingAgent] ❌ VLM call error: {e}", flush=True)
            return None, "I'm having a bit of trouble seeing the page. Could you tell me what you see?", False
    
    def _parse_tool_from_text(self, text: str) -> Optional[dict]:
        """
        Fallback: Parse tool call from text content when VLM writes JSON instead of using tool_calls.
        
        Handles formats like:
        - ```json\n{"name": "click", "parameters": {"element": "Next"}}\n```
        - {"recipient_name": "functions.click", "parameters": {"element": "Next"}}
        """
        # Try to find JSON in the text
        json_patterns = [
            r'```json\s*(\{.*?\})\s*```',  # ```json {...} ```
            r'```\s*(\{.*?\})\s*```',       # ``` {...} ```
            r'(\{[^{}]*"(?:name|recipient_name|function)"[^{}]*\})',  # Inline JSON with tool-like keys
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    
                    # Handle different JSON formats VLM might output
                    tool_name = None
                    arguments = {}
                    
                    # Format 1: {"name": "click", "arguments": {...}}
                    if "name" in data:
                        tool_name = data["name"]
                        arguments = data.get("arguments", data.get("parameters", {}))
                    
                    # Format 2: {"recipient_name": "functions.click", "parameters": {...}}
                    elif "recipient_name" in data:
                        # Extract tool name from "functions.click" -> "click"
                        recipient = data["recipient_name"]
                        if "." in recipient:
                            tool_name = recipient.split(".")[-1]
                        else:
                            tool_name = recipient
                        arguments = data.get("parameters", {})
                    
                    # Format 3: {"function": "click", "element": "Next"}
                    elif "function" in data:
                        tool_name = data["function"]
                        arguments = {k: v for k, v in data.items() if k != "function"}
                    
                    if tool_name:
                        return {"name": tool_name, "arguments": arguments}
                        
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def _clean_json_from_speech(self, text: str) -> str:
        """
        Remove JSON blocks from speech text so we don't speak the JSON to the user.
        """
        # Remove ```json ... ``` blocks
        text = re.sub(r'```json\s*\{.*?\}\s*```', '', text, flags=re.DOTALL)
        # Remove ``` ... ``` blocks
        text = re.sub(r'```\s*\{.*?\}\s*```', '', text, flags=re.DOTALL)
        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n', '\n', text).strip()
        
        return text
    
    async def _sanitize_speech(self, raw_speech: str) -> str:
        """
        Clean up VLM speech output before speaking to user.
        
        Removes JSON, numbered lists, and verbose analysis.
        Uses LLM to rephrase if needed.
        """
        # First, try simple regex cleanup
        cleaned = self._clean_json_from_speech(raw_speech)
        
        # Remove numbered observation lists (1. This is... 2. The calendar...)
        cleaned = re.sub(r'^\d+\.\s+[^\n]+\n?', '', cleaned, flags=re.MULTILINE)
        cleaned = cleaned.strip()
        
        # If there's still content and it looks clean, use it
        if cleaned and len(cleaned) < 200 and '```' not in cleaned and '{' not in cleaned:
            return cleaned
        
        # Otherwise, use LLM to extract just the conversational part
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": f"""Extract ONLY the conversational spoken response from this text. 
Remove any JSON, code blocks, numbered lists, or technical analysis.
Keep it to 1-2 short sentences max.

Text: {raw_speech}

Conversational response:"""
                }],
                max_tokens=100,
                temperature=0
            )
            result = response.choices[0].message.content.strip()
            if result:
                return result
        except Exception as e:
            print(f"[SchedulingAgent] ⚠️ Speech sanitize error: {e}", flush=True)
        
        # Fallback: return cleaned version or a default
        return cleaned if cleaned else "Let me help you with that."
    
    async def _extract_info_from_message(self, user_message: str) -> None:
        """
        Use LLM to extract date/time/name/email from user message.
        This updates the goal dynamically.
        """
        prompt = get_info_extraction_prompt(user_message, self.collected_info)
        
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",  # Fast model for simple extraction
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content or "{}")
            
            # Update collected info with any new values
            for key in ['date', 'time', 'name', 'email']:
                if result.get(key) and result[key] != "null":
                    old_value = self.collected_info[key]
                    new_value = result[key]
                    
                    if old_value != new_value:
                        self.collected_info[key] = new_value
                        print(f"[SchedulingAgent] 📝 Extracted {key}: '{new_value}'", flush=True)
                        if old_value:
                            print(f"[SchedulingAgent] 🔄 (Changed from '{old_value}')", flush=True)
                        
        except Exception as e:
            print(f"[SchedulingAgent] ⚠️ Info extraction error: {e}", flush=True)
    
    async def _execute_tool(self, tool_call: Optional[dict]) -> bool:
        """
        Execute the tool chosen by the VLM.
        
        Returns:
            True if the action succeeded, False otherwise.
        """
        if not tool_call:
            print(f"[SchedulingAgent] ℹ️ No tool to execute", flush=True)
            return False
        
        tool_name = tool_call["name"]
        args = tool_call["arguments"]
        
        print(f"[SchedulingAgent] 🔧 Executing: {tool_name}({args})", flush=True)
        
        if tool_name == "click":
            element = args.get("element", "")
            if element and self.browser:
                print(f"[SchedulingAgent] 🖱️ Clicking: '{element}'", flush=True)
                
                # Method 1: Use LLM to find a precise selector for complex elements
                print(f"[SchedulingAgent] 🧠 Using LLM to find element...", flush=True)
                selector = await self._llm_find_element(element)
                if selector:
                    print(f"[SchedulingAgent] 🎯 LLM found selector: '{selector}'", flush=True)
                    success = await self._try_click_selector(selector)
                    if success:
                        print(f"[SchedulingAgent] ✅ Click successful (LLM selector)", flush=True)
                        await asyncio.sleep(0.5)
                        return True
                    print(f"[SchedulingAgent] ⚠️ LLM selector failed, trying fallbacks...", flush=True)
                
                # Method 2: Try smart_click for simple elements (dates, times, text buttons)
                print(f"[SchedulingAgent] 🔄 Trying smart_click...", flush=True)
                success = await self.browser.smart_click(element)
                if success:
                    print(f"[SchedulingAgent] ✅ Click successful (smart_click)", flush=True)
                    await asyncio.sleep(0.5)
                    return True
                
                # Method 3: Try direct text selector as last resort
                print(f"[SchedulingAgent] 🔄 Trying text selector...", flush=True)
                success = await self.browser.click(f"text={element}", timeout=2000)
                if success:
                    print(f"[SchedulingAgent] ✅ Click successful (text selector)", flush=True)
                    return True
                
                print(f"[SchedulingAgent] ❌ All click methods failed", flush=True)
                return False
            return False
        
        elif tool_name == "scroll":
            direction = args.get("direction", "down")
            if self.browser:
                print(f"[SchedulingAgent] 📜 Scrolling: {direction}", flush=True)
                
                # Use LLM to find the scrollable container
                print(f"[SchedulingAgent] 🧠 Finding scrollable container...", flush=True)
                selector = await self._llm_find_scrollable()
                
                if selector:
                    print(f"[SchedulingAgent] 🎯 Found scrollable: '{selector}'", flush=True)
                    success = await self._scroll_element(selector, direction)
                    if success:
                        print(f"[SchedulingAgent] ✅ Scrolled container {direction}", flush=True)
                        await asyncio.sleep(0.3)
                        return True
                    print(f"[SchedulingAgent] ⚠️ Container scroll failed, trying page scroll...", flush=True)
                
                # Fallback to page scroll
                await self.browser.scroll(direction)
                await asyncio.sleep(0.3)
                print(f"[SchedulingAgent] ✅ Scrolled page {direction}", flush=True)
                return True
            return False
        
        elif tool_name == "type_text":
            field_desc = args.get("field_description", "")
            text = args.get("text", "")
            if field_desc and text and self.browser:
                print(f"[SchedulingAgent] ⌨️ Typing '{text}' into '{field_desc}'", flush=True)
                success = await self._type_in_field(field_desc, text)
                if success:
                    print(f"[SchedulingAgent] ✅ Typed successfully", flush=True)
                    return True
                else:
                    print(f"[SchedulingAgent] ❌ Typing failed", flush=True)
                    return False
            return False
        
        elif tool_name == "go_back":
            if self.browser and self.browser.page:
                print(f"[SchedulingAgent] ⬅️ Going back", flush=True)
                await self.browser.page.go_back()
                await asyncio.sleep(0.5)
                print(f"[SchedulingAgent] ✅ Went back", flush=True)
                return True
            return False
        
        elif tool_name == "ask_user":
            question = args.get("question", "")
            print(f"[SchedulingAgent] ❓ Asking user: '{question}'", flush=True)
            return True  # ask_user is always "successful"
        
        elif tool_name == "done":
            summary = args.get("summary", "Booking complete!")
            print(f"[SchedulingAgent] 🎉 GOAL COMPLETE: {summary}", flush=True)
            self.goal_complete = True
            self.is_active = False
            return True
        
        else:
            print(f"[SchedulingAgent] ⚠️ Unknown tool: {tool_name}", flush=True)
            return False
    
    async def _type_in_field(self, field_description: str, text: str) -> bool:
        """
        Type text into a form field identified by description.
        
        Tries multiple strategies to find and fill the field.
        """
        if not self.browser or not self.browser.page:
            return False
        
        page = self.browser.page
        field_lower = field_description.lower()
        
        # Strategy 1: Try common selectors based on field description
        selectors_to_try = []
        
        if "name" in field_lower:
            selectors_to_try = [
                'input[name="name"]',
                'input[placeholder*="name" i]',
                'input[aria-label*="name" i]',
                'input[type="text"]:first-of-type',
            ]
        elif "email" in field_lower:
            selectors_to_try = [
                'input[type="email"]',
                'input[name="email"]',
                'input[placeholder*="email" i]',
                'input[aria-label*="email" i]',
            ]
        elif "phone" in field_lower:
            selectors_to_try = [
                'input[type="tel"]',
                'input[name="phone"]',
                'input[placeholder*="phone" i]',
            ]
        
        # Try each selector
        for selector in selectors_to_try:
            try:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    await locator.first.fill(text)
                    print(f"[SchedulingAgent] ✅ Filled via selector: {selector}", flush=True)
                    return True
            except Exception:
                continue
        
        # Strategy 2: Try clicking near the label and typing
        try:
            label_locator = page.get_by_text(field_description, exact=False)
            if await label_locator.count() > 0:
                parent = label_locator.first.locator("..").locator("input")
                if await parent.count() > 0:
                    await parent.first.fill(text)
                    print(f"[SchedulingAgent] ✅ Filled via label proximity", flush=True)
                    return True
        except Exception:
            pass
        
        print(f"[SchedulingAgent] ⚠️ Could not find field: {field_description}", flush=True)
    
    async def _llm_find_element(self, element_description: str) -> Optional[str]:
        """
        Use LLM to analyze the DOM and find a precise selector for an element.
        
        Args:
            element_description: Natural language description like "next month arrow"
            
        Returns:
            A CSS selector, aria-label query, or text content that can be used to click
        """
        if not self.browser or not self.browser.page:
            return None
        
        try:
            # Get the DOM content
            page = self.browser.page
            
            # Get relevant HTML - focus on ENABLED clickable elements only
            dom_content = await page.evaluate("""() => {
                const clickables = document.querySelectorAll('button, a, [role="button"], [onclick], [aria-label], svg, [class*="arrow"], [class*="next"], [class*="prev"], [class*="nav"]');
                const elements = [];
                clickables.forEach((el, idx) => {
                    // SKIP DISABLED ELEMENTS - they can't be clicked!
                    if (el.disabled || el.getAttribute('disabled') !== null || el.getAttribute('aria-disabled') === 'true') {
                        return;  // Skip this element
                    }
                    
                    const info = {
                        tag: el.tagName.toLowerCase(),
                        text: el.textContent?.trim().substring(0, 50) || '',
                        ariaLabel: el.getAttribute('aria-label') || '',
                        className: el.className?.toString().substring(0, 100) || '',
                        id: el.id || '',
                        role: el.getAttribute('role') || '',
                        title: el.getAttribute('title') || '',
                        dataTestId: el.getAttribute('data-testid') || ''
                    };
                    // Only include elements with some identifying info
                    if (info.text || info.ariaLabel || info.className || info.id || info.title) {
                        elements.push(info);
                    }
                });
                return JSON.stringify(elements.slice(0, 50));  // Limit to 50 elements
            }""")
            
            print(f"[SchedulingAgent] 📄 DOM elements found: {len(json.loads(dom_content))}", flush=True)
            
            # Ask LLM to find the element
            response = await self.client.chat.completions.create(
                model="gpt-4.1-mini",  # Faster model for this task
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert at finding web elements. Given a list of DOM elements and a description, 
return ONLY a selector that can be used with Playwright to click the element.

SELECTOR FORMATS (in order of preference):
1. text content: button:has-text("Next") or text=Next
2. aria-label: [aria-label="Go to next month"]
3. CSS selector: button.next-arrow
4. data-testid: [data-testid="next-button"]

IMPORTANT DISTINCTIONS:
- "blue Next button" or "booking Next" = The button with text "Next" for proceeding with booking
- "next month arrow" or "calendar arrow" = Navigation arrow for changing months (aria-label contains "month")
- If description says "blue" or "next to time" = Look for button with text="Next", NOT month navigation

RULES:
- Return ONLY the selector, nothing else
- No explanation, no quotes around the whole thing
- For booking progression, prefer button:has-text("Next")
- For month navigation, prefer aria-label selectors
- Be specific but not overly brittle"""
                    },
                    {
                        "role": "user",
                        "content": f"""Find this element: "{element_description}"

DOM elements:
{dom_content}"""
                    }
                ],
                max_tokens=100,
                temperature=0
            )
            
            selector = response.choices[0].message.content.strip()
            # Clean up common formatting issues
            selector = selector.strip('"\'`')
            
            return selector if selector else None
            
        except Exception as e:
            print(f"[SchedulingAgent] ❌ LLM element finding failed: {e}", flush=True)
            return None
    
    async def _try_click_selector(self, selector: str) -> bool:
        """
        Try to click an element using a selector from the LLM.
        Handles various selector formats.
        """
        if not self.browser or not self.browser.page:
            return False
        
        page = self.browser.page
        
        try:
            # Try as-is first (works for most Playwright selectors)
            locator = page.locator(selector)
            if await locator.count() > 0:
                await locator.first.click(timeout=3000)
                return True
        except Exception as e:
            print(f"[SchedulingAgent] ⚠️ Direct selector failed: {e}", flush=True)
        
        # Try as text selector if it looks like text
        if not selector.startswith('[') and not selector.startswith('.') and not selector.startswith('#'):
            try:
                locator = page.get_by_text(selector, exact=False)
                if await locator.count() > 0:
                    await locator.first.click(timeout=3000)
                    return True
            except Exception:
                pass
        
        # Try as aria-label if it contains aria-label
        if 'aria-label' in selector.lower():
            try:
                # Extract the label value
                match = re.search(r'aria-label[=~*]*["\']?([^"\'>\]]+)["\']?', selector)
                if match:
                    label = match.group(1)
                    locator = page.get_by_label(label)
                    if await locator.count() > 0:
                        await locator.first.click(timeout=3000)
                        return True
            except Exception:
                pass
        
        # Try as role with name if it contains role
        if ':has-text' in selector or 'role=' in selector:
            try:
                # Try to parse button:has-text("X") format
                match = re.search(r'(\w+):has-text\(["\']?([^"\']+)["\']?\)', selector)
                if match:
                    role, text = match.groups()
                    locator = page.get_by_role(role, name=text)
                    if await locator.count() > 0:
                        await locator.first.click(timeout=3000)
                        return True
            except Exception:
                pass
        
        return False
    
    async def _llm_find_scrollable(self) -> Optional[str]:
        """
        Use LLM to find the main scrollable container on the page.
        
        Returns:
            A CSS selector for the scrollable element, or None if not found.
        """
        if not self.browser or not self.browser.page:
            return None
        
        try:
            page = self.browser.page
            
            # Get potential scrollable elements
            dom_content = await page.evaluate("""() => {
                const scrollables = [];
                
                // Find elements that are scrollable
                const allElements = document.querySelectorAll('*');
                allElements.forEach((el) => {
                    const style = window.getComputedStyle(el);
                    const overflowY = style.overflowY;
                    const overflowX = style.overflowX;
                    
                    // Check if element is scrollable
                    const isScrollable = (
                        (overflowY === 'auto' || overflowY === 'scroll' || 
                         overflowX === 'auto' || overflowX === 'scroll') &&
                        (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth)
                    );
                    
                    if (isScrollable && el.tagName !== 'HTML' && el.tagName !== 'BODY') {
                        const info = {
                            tag: el.tagName.toLowerCase(),
                            className: el.className?.toString().substring(0, 100) || '',
                            id: el.id || '',
                            role: el.getAttribute('role') || '',
                            ariaLabel: el.getAttribute('aria-label') || '',
                            scrollHeight: el.scrollHeight,
                            clientHeight: el.clientHeight,
                            hasTimeSlots: el.textContent?.includes(':00') || el.textContent?.includes(':30') || false
                        };
                        scrollables.push(info);
                    }
                });
                
                return JSON.stringify(scrollables.slice(0, 20));
            }""")
            
            scrollables = json.loads(dom_content)
            print(f"[SchedulingAgent] 📄 Scrollable elements found: {len(scrollables)}", flush=True)
            
            if not scrollables:
                return None
            
            # Ask LLM to pick the best one
            response = await self.client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are finding the main scrollable container on a scheduling page.
Look for the container that holds time slots or calendar content.

Return ONLY a valid CSS selector for the scrollable element. Prefer:
1. Elements with time-related content (hasTimeSlots=true)
2. Elements with large scrollHeight
3. Elements with meaningful class names

VALID CSS SELECTOR FORMATS:
- .classname (class selector - starts with dot)
- div.classname (element + class)
- #id (id selector)
- [role="listbox"] (attribute selector)

WRONG formats (do NOT use):
- .div.classname (WRONG - don't put .div.)
- div .classname (WRONG - no space)

Return ONLY the selector, nothing else."""
                    },
                    {
                        "role": "user",
                        "content": f"""Find the main scrollable container:

{json.dumps(scrollables, indent=2)}"""
                    }
                ],
                max_tokens=50,
                temperature=0
            )
            
            selector = response.choices[0].message.content.strip().strip('"\'`')
            return selector if selector else None
            
        except Exception as e:
            print(f"[SchedulingAgent] ❌ LLM scrollable finding failed: {e}", flush=True)
            return None
    
    async def _scroll_element(self, selector: str, direction: str) -> bool:
        """
        Scroll a specific element by selector.
        
        Args:
            selector: CSS selector for the scrollable element
            direction: 'up' or 'down'
        """
        if not self.browser or not self.browser.page:
            return False
        
        try:
            page = self.browser.page
            amount = 300 if direction == "down" else -300
            
            # Clean up selector - fix common LLM mistakes
            clean_selector = selector.strip()
            # Fix ".div." -> "div." or just "."
            if clean_selector.startswith('.div.'):
                clean_selector = clean_selector[4:]  # Remove ".div" prefix, keep the "."
            elif clean_selector.startswith('div.'):
                pass  # Already correct
            # Remove any accidental double dots
            clean_selector = clean_selector.replace('..', '.')
            
            print(f"[SchedulingAgent] 📜 Clean selector: '{clean_selector}'", flush=True)
            
            # Try to scroll the element - pass args as single object for Playwright Python
            scrolled = await page.evaluate(
                """(args) => {
                    const el = document.querySelector(args.selector);
                    if (el) {
                        const before = el.scrollTop;
                        el.scrollBy(0, args.amount);
                        return el.scrollTop !== before;
                    }
                    return false;
                }""",
                {"selector": clean_selector, "amount": amount}
            )
            
            return scrolled
            
        except Exception as e:
            print(f"[SchedulingAgent] ⚠️ Element scroll failed: {e}", flush=True)
            return False
    
    def reset(self) -> None:
        """Reset the agent state for a new scheduling session."""
        print(f"[SchedulingAgent] 🔄 Resetting state", flush=True)
        self.is_active = False
        self.goal_complete = False
        self.collected_info = {
            'date': None,
            'time': None,
            'name': None,
            'email': None
        }
