"""
Calendly Service - Handles all Calendly scheduling interactions.

Extracted from ai_agent.py for better modularity.
Manages the full scheduling flow: opening Calendly, date/time selection,
form filling, and confirmation.
"""

import asyncio
from typing import Optional, Callable, Awaitable, Any
from openai import AsyncOpenAI
from app.core.config import get_settings


class CalendlyService:
    """
    Service for handling Calendly scheduling interactions.
    
    This service manages the entire scheduling flow:
    1. Opening Calendly link
    2. Handling date/time selection
    3. Filling booking form
    4. Confirming booking
    """
    
    def __init__(
        self,
        browser_session,
        speak_callback: Callable[[str], Awaitable[None]],
        memory_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        save_user_info_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
    ):
        """
        Initialize CalendlyService.
        
        Args:
            browser_session: Active browser session for page interaction
            speak_callback: Async function to speak text (calls TTS)
            memory_callback: Optional callback to save messages to memory
            save_user_info_callback: Optional callback to save user contact info (name, email)
        """
        self.browser = browser_session
        self._speak = speak_callback
        self._save_to_memory = memory_callback
        self._save_user_info = save_user_info_callback
        
        # State management
        self.awaiting_scheduling_confirmation = False
        self.on_calendly = False
        self.awaiting_info = False
        self.awaiting_confirmation = False
        self.user_info = {}
        
        # OpenAI client for LLM calls
        settings = get_settings()
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    async def _speak_and_save(self, response: str, user_message: str = None) -> None:
        """Speak a response and save both user message and response to memory."""
        await self._speak(response)
        if self._save_to_memory:
            if user_message:
                await self._save_to_memory("user", user_message)
            await self._save_to_memory("assistant", response)
    
    def reset_state(self) -> None:
        """Reset all Calendly state flags."""
        self.awaiting_scheduling_confirmation = False
        self.on_calendly = False
        self.awaiting_info = False
        self.awaiting_confirmation = False
        self.user_info = {}
    
    def is_active(self) -> bool:
        """Check if any Calendly interaction is in progress."""
        return (
            self.awaiting_scheduling_confirmation or
            self.on_calendly or
            self.awaiting_info or
            self.awaiting_confirmation
        )
    
    async def open_calendly(self, calendly_url: str, scheduling_message: str) -> None:
        """
        Open Calendly link in browser and speak scheduling message.
        
        Args:
            calendly_url: URL of the Calendly page
            scheduling_message: Message to speak when opening calendar
        """
        self.awaiting_scheduling_confirmation = False
        
        if calendly_url and self.browser:
            print(f"[Calendly] 📅 Opening: {calendly_url}", flush=True)
            await self._speak(scheduling_message)
            await self.browser.navigate(calendly_url)
            await asyncio.sleep(1.0)  # Wait for Calendly to load
            self.on_calendly = True
            print(f"[Calendly] ✓ Opened, ready for scheduling", flush=True)
        else:
            await self._speak("I'd love to help you schedule, but I don't have the calendar link handy. You can reach out directly to schedule a call!")
        
        # Save to memory
        if self._save_to_memory:
            await self._save_to_memory("assistant", scheduling_message)
    
    async def handle_interaction(self, user_message: str) -> None:
        """
        Handle user interactions on Calendly page (day/time selection).
        
        Args:
            user_message: What the user said
        """
        # Save user message to memory
        if self._save_to_memory:
            await self._save_to_memory("user", user_message)
        
        # Get current page
        page = self.browser.page if self.browser else None
        if not page:
            await self._speak_and_save("I'm having trouble with the calendar. Could you try again?")
            return
        
        # Check intent: select, scroll, or back
        try:
            intent = await self._detect_calendly_intent(user_message)
            print(f"[Calendly] 📅 Intent: {intent}", flush=True)
            
            if intent == "scroll":
                await self._handle_scroll(page)
                return
            
            if intent == "back":
                await self._handle_back(page)
                return
                
        except Exception as e:
            print(f"[Calendly] ⚠️ Error checking intent: {e}", flush=True)
        
        # Default: try to click something
        await self._handle_selection(page, user_message)
    
    async def fill_form(self, user_message: str) -> None:
        """
        Fill in the Calendly booking form with user's name and email.
        
        Args:
            user_message: User's message containing their info
        """
        # Save user message to memory
        if self._save_to_memory:
            await self._save_to_memory("user", user_message)
        
        # First check if user wants to change date/time instead
        try:
            intent = await self._detect_form_intent(user_message)
            print(f"[Calendly] 📅 Form intent: {intent}", flush=True)
            
            if intent == "change_time":
                print(f"[Calendly] 📅 User wants to change date/time, going back", flush=True)
                self.awaiting_info = False
                page = self.browser.page if self.browser else None
                if page:
                    await self._navigate_back(page)
                await self.handle_interaction(user_message)
                return
        except Exception as e:
            print(f"[Calendly] ⚠️ Error checking form intent: {e}", flush=True)
        
        # Extract name and email
        name, email = await self._extract_contact_info(user_message)
        
        # Check what we're missing
        if not name and not email:
            await self._speak_and_save("I didn't catch that. Could you tell me your name and email?")
            return
        elif not name:
            await self._speak_and_save(f"Got your email. What's your name?")
            return
        elif not email:
            await self._speak_and_save(f"Thanks {name}! What's your email address?")
            return
        
        # We have both - fill the form
        page = self.browser.page if self.browser else None
        if not page:
            await self._speak_and_save("I'm having trouble with the form. Could you try again?")
            return
        
        print(f"[Calendly] 📅 Filling form - Name: {name}, Email: {email}", flush=True)
        
        # Fill name field
        await self._fill_name_field(page, name)
        
        # Fill email field
        await self._fill_email_field(page, email)
        
        await asyncio.sleep(0.3)
        
        # Store info and ask for confirmation
        self.user_info = {'name': name, 'email': email}
        self.awaiting_info = False
        self.awaiting_confirmation = True
        
        await self._speak_and_save(f"I've filled in {name} with email {email}. Does that look correct? Say yes to confirm or let me know what to change.")
    
    async def handle_confirmation(self, user_message: str) -> None:
        """
        Handle user's confirmation or correction of booking info.
        
        Args:
            user_message: User's confirmation or correction
        """
        # Save user message to memory
        if self._save_to_memory:
            await self._save_to_memory("user", user_message)
        
        name = self.user_info.get('name', '')
        email = self.user_info.get('email', '')
        
        # Detect intent: confirm, change, or cancel
        intent, new_name, new_email = await self._detect_confirmation_intent(
            user_message, name, email
        )
        
        if intent == "cancel":
            self.awaiting_confirmation = False
            self.on_calendly = False
            await self._speak_and_save("No problem, we can skip the scheduling for now. Is there anything else I can help you with?")
            return
        
        if intent in ["change_name", "change_email", "change_both"]:
            self.user_info = {'name': new_name, 'email': new_email}
            
            page = self.browser.page if self.browser else None
            if page:
                if intent in ["change_name", "change_both"]:
                    await self._fill_name_field(page, new_name)
                if intent in ["change_email", "change_both"]:
                    await self._fill_email_field(page, new_email)
            
            await self._speak_and_save(f"Updated! Now showing {new_name} with email {new_email}. Does that look right?")
            return
        
        # Intent is confirm - click schedule button
        await self._complete_booking(name)
    
    # ==================== PRIVATE HELPER METHODS ====================
    
    async def _detect_calendly_intent(self, user_message: str) -> str:
        """Use LLM to detect user's intent on Calendly page."""
        prompt = f"""The user is on a Calendly scheduling page. They said: "{user_message}"

What is the user's intent?
- "select" = They mention a SPECIFIC date (like "January 5th", "the 12th", "Monday") OR a specific time (like "10am", "2:30")
- "scroll" = They want to scroll to see more times (like "scroll down", "show more", "see other times")
- "back" = They want to go back to the previous page, exit scheduling, or cancel

IMPORTANT: If they mention ANY specific date or time, answer "select".

Answer ONLY one word: "back", "scroll", or "select"."""
        
        response = await self.client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0
        )
        return response.choices[0].message.content.strip().lower()
    
    async def _handle_scroll(self, page) -> None:
        """Handle scroll request on Calendly."""
        print(f"[Calendly] 📅 User wants to scroll", flush=True)
        try:
            # Target the Calendly time slots container
            scrolled = await page.evaluate("""
                () => {
                    const spotlist = document.querySelector('[class*="spotlist-list"]') ||
                                    document.querySelector('[class*="booking-kit_spotlist"]');
                    if (spotlist && spotlist.scrollHeight > spotlist.clientHeight) {
                        spotlist.scrollBy(0, 200);
                        return 'spotlist';
                    }
                    
                    const allDivs = document.querySelectorAll('div');
                    for (const div of allDivs) {
                        const style = getComputedStyle(div);
                        if ((style.overflow === 'auto' || style.overflowY === 'auto') &&
                            div.scrollHeight > div.clientHeight && 
                            div.clientHeight > 100) {
                            div.scrollBy(0, 200);
                            return 'overflow-auto';
                        }
                    }
                    return null;
                }
            """)
            
            if scrolled:
                print(f"[Calendly] ✓ Scrolled using {scrolled}", flush=True)
            else:
                print(f"[Calendly] ⚠️ No scrollable container found", flush=True)
            
            await asyncio.sleep(0.3)
            await self._speak_and_save("Here you go! Let me know which time works for you.")
        except Exception as e:
            print(f"[Calendly] ⚠️ Could not scroll: {e}", flush=True)
            await self._speak_and_save("I'm having trouble scrolling. You can scroll manually to see more times.")
    
    async def _handle_back(self, page) -> None:
        """Handle back navigation on Calendly."""
        print(f"[Calendly] 📅 User wants to go back", flush=True)
        try:
            await self._navigate_back(page)
            self.awaiting_info = False
            await self._speak_and_save("No problem! Here's the calendar again. Which date works better for you?")
        except Exception as e:
            print(f"[Calendly] ⚠️ Could not go back: {e}", flush=True)
    
    async def _navigate_back(self, page) -> None:
        """Navigate back on Calendly page."""
        back_clicked = False
        for selector in ['button:has-text("Back")', 'button:has-text("←")', '[aria-label*="back" i]', '[aria-label*="previous" i]']:
            try:
                await page.click(selector, timeout=1000)
                back_clicked = True
                print(f"[Calendly] ✓ Clicked back button", flush=True)
                break
            except:
                continue
        
        if not back_clicked:
            await page.go_back()
            print(f"[Calendly] ✓ Used browser back", flush=True)
        
        await asyncio.sleep(0.5)
    
    async def _handle_selection(self, page, user_message: str) -> None:
        """Handle date/time selection on Calendly."""
        # Extract clickable elements
        clickable_elements = await page.evaluate("""
            () => {
                const elements = [];
                
                document.querySelectorAll('button').forEach(el => {
                    const text = el.textContent.trim();
                    const ariaLabel = el.getAttribute('aria-label') || '';
                    const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                    
                    if (disabled || !text) return;
                    
                    if (/^\\d{1,2}$/.test(text)) {
                        elements.push({type: 'date', text: text, ariaLabel: ariaLabel});
                    }
                    else if (text.match(/\\d{1,2}:\\d{2}/) || text.match(/\\d{1,2}\\s*(am|pm|AM|PM)/)) {
                        elements.push({type: 'time', text: text});
                    }
                    else if (text.toLowerCase().includes('next') || 
                             text.toLowerCase().includes('confirm') || 
                             text.toLowerCase().includes('schedule')) {
                        elements.push({type: 'action', text: text});
                    }
                });
                
                document.querySelectorAll('td[role="button"], td[tabindex="0"], [role="gridcell"] button').forEach(el => {
                    const text = el.textContent.trim();
                    if (/^\\d{1,2}$/.test(text) && !el.getAttribute('aria-disabled')) {
                        elements.push({type: 'date', text: text, ariaLabel: el.getAttribute('aria-label') || ''});
                    }
                });
                
                return elements;
            }
        """)
        
        print(f"[Calendly] 📅 Elements found: {clickable_elements[:10]}...", flush=True)
        
        # Use LLM to determine what to click
        target_text = await self._determine_click_target(user_message, clickable_elements)
        print(f"[Calendly] 📅 LLM says click: '{target_text}'", flush=True)
        
        if target_text == "NONE" or not target_text:
            await self._speak_and_save("I couldn't find that on the calendar. Could you try saying the day or time again?")
            return
        
        # Try to click
        clicked = await self._click_element(page, target_text)
        
        if clicked:
            await asyncio.sleep(0.5)
            
            # Check if we clicked a time (need to click Next)
            if any(c in target_text.lower() for c in ['am', 'pm', ':']):
                await self._click_next_after_time(page)
            else:
                await self._speak_and_save("Perfect! Now which time slot works for you?")
        else:
            await self._speak_and_save("I couldn't click that. Could you try saying it differently?")
            print(f"[Calendly] ⚠️ Failed to click: '{target_text}'", flush=True)
    
    async def _determine_click_target(self, user_message: str, elements: list) -> str:
        """Use LLM to determine what element to click."""
        prompt = f"""The user is on a Calendly scheduling page. They said: "{user_message}"

Available clickable elements on the page:
{elements}

What should I click?

RULES:
- For DATES (like "January 5th", "the 5th") → respond with just the number: "5"
- For TIMES (like "5am", "10:30am", "2pm") → respond with EXACT time text from the list: "5:00am" or "10:30am"
- For confirm/next → respond with "Next" or "Confirm"

IMPORTANT: If user says a TIME like "5am", find the matching time in the list (e.g., "5:00am") - do NOT respond with just "5"!

Respond with ONLY the exact text to click. If nothing matches, respond "NONE"."""

        response = await self.client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0
        )
        return response.choices[0].message.content.strip()
    
    async def _click_element(self, page, target_text: str) -> bool:
        """Click an element by text."""
        try:
            await page.locator(f'button:has-text("{target_text}")').first.click(timeout=500)
            print(f"[Calendly] ✓ Clicked: '{target_text}'", flush=True)
            return True
        except:
            # Fallback: JS click
            try:
                await page.evaluate("""
                    (targetText) => {
                        const buttons = document.querySelectorAll('button');
                        for (const btn of buttons) {
                            if (btn.textContent.trim() === targetText || 
                                btn.textContent.toLowerCase().includes(targetText.toLowerCase())) {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """, target_text)
                print(f"[Calendly] ✓ Clicked (JS): '{target_text}'", flush=True)
                return True
            except:
                return False
    
    async def _click_next_after_time(self, page) -> None:
        """Click Next button after selecting a time."""
        await asyncio.sleep(0.8)
        
        next_clicked = await page.evaluate("""
            () => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    const text = btn.textContent.trim().toLowerCase();
                    if (text === 'next' || text.includes('next')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        
        if next_clicked:
            print(f"[Calendly] ✓ Clicked Next button", flush=True)
            await asyncio.sleep(0.5)
            self.awaiting_info = True
            await self._speak_and_save("Got it! What's your name and email so I can confirm the booking?")
        else:
            print(f"[Calendly] ⚠️ Next button not found", flush=True)
            await self._speak_and_save("I selected the time. Could you click Next to continue?")
    
    async def _detect_form_intent(self, user_message: str) -> str:
        """Detect if user wants to change time or provide info."""
        prompt = f"""The user was asked for their name and email to book a meeting. They said: "{user_message}"

What is their intent?
- "change_time" = They want to go back and pick a different date or time (mentions a day, date, or wants to change)
- "provide_info" = They are providing their name and/or email

Answer ONLY: "change_time" or "provide_info"."""

        response = await self.client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0
        )
        return response.choices[0].message.content.strip().lower()
    
    async def _extract_contact_info(self, user_message: str) -> tuple:
        """Extract name and email from user's message."""
        prompt = f"""Extract the name and email from this message: "{user_message}"

The user is providing their contact info for a calendar booking.

Respond in this exact format (nothing else):
NAME: [extracted name or MISSING]
EMAIL: [extracted email or MISSING]

Examples:
- "John Smith, john@email.com" → NAME: John Smith, EMAIL: john@email.com
- "My name is Sarah and email is sarah@test.com" → NAME: Sarah, EMAIL: sarah@test.com
- "just use mehdi@gmail.com" → NAME: MISSING, EMAIL: mehdi@gmail.com"""

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0
            )
            result = response.choices[0].message.content.strip()
            print(f"[Calendly] 📅 Extracted info: {result}", flush=True)
            
            name = None
            email = None
            for line in result.split('\n'):
                if line.startswith('NAME:'):
                    val = line.replace('NAME:', '').strip()
                    if val and val != 'MISSING':
                        name = val
                elif line.startswith('EMAIL:'):
                    val = line.replace('EMAIL:', '').strip()
                    if val and val != 'MISSING':
                        email = val
            
            return name, email
        except Exception as e:
            print(f"[Calendly] ⚠️ Error extracting info: {e}", flush=True)
            return None, None
    
    async def _fill_name_field(self, page, name: str) -> None:
        """Fill the name field on Calendly form."""
        try:
            name_filled = False
            for selector in ['input[name="full_name"]', 'input[name="name"]', 'input[placeholder*="name" i]', 'input[aria-label*="name" i]']:
                try:
                    await page.locator(selector).first.fill(name, timeout=1000)
                    name_filled = True
                    print(f"[Calendly] ✓ Filled name with selector: {selector}", flush=True)
                    break
                except:
                    continue
            
            if not name_filled:
                await page.locator('input[type="text"]').first.fill(name, timeout=2000)
                print(f"[Calendly] ✓ Filled name (fallback)", flush=True)
        except Exception as e:
            print(f"[Calendly] ⚠️ Failed to fill name: {e}", flush=True)
    
    async def _fill_email_field(self, page, email: str) -> None:
        """Fill the email field on Calendly form."""
        try:
            email_filled = False
            for selector in ['input[name="email"]', 'input[type="email"]', 'input[placeholder*="email" i]', 'input[aria-label*="email" i]']:
                try:
                    await page.locator(selector).first.fill(email, timeout=1000)
                    email_filled = True
                    print(f"[Calendly] ✓ Filled email with selector: {selector}", flush=True)
                    break
                except:
                    continue
            
            if not email_filled:
                print(f"[Calendly] ⚠️ Could not find email field", flush=True)
        except Exception as e:
            print(f"[Calendly] ⚠️ Failed to fill email: {e}", flush=True)
    
    async def _detect_confirmation_intent(self, user_message: str, name: str, email: str) -> tuple:
        """Detect user's intent for confirmation: confirm, change, or cancel."""
        prompt = f"""The user was asked to confirm their booking info: Name="{name}", Email="{email}"
They responded: "{user_message}"

What is their intent?
- "confirm" = they're happy with the info, proceed with booking
- "change_name" = they want to change their name (extract new name)
- "change_email" = they want to change their email (extract new email)  
- "change_both" = they want to change both (extract new values)
- "cancel" = they want to cancel/go back

Respond in format:
INTENT: [confirm/change_name/change_email/change_both/cancel]
NEW_NAME: [new name if changing, otherwise SAME]
NEW_EMAIL: [new email if changing, otherwise SAME]"""

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0
            )
            result = response.choices[0].message.content.strip()
            print(f"[Calendly] 📅 Confirmation response: {result}", flush=True)
            
            intent = "confirm"
            new_name = name
            new_email = email
            
            for line in result.split('\n'):
                if line.startswith('INTENT:'):
                    intent = line.replace('INTENT:', '').strip().lower()
                elif line.startswith('NEW_NAME:'):
                    val = line.replace('NEW_NAME:', '').strip()
                    if val and val != 'SAME':
                        new_name = val
                elif line.startswith('NEW_EMAIL:'):
                    val = line.replace('NEW_EMAIL:', '').strip()
                    if val and val != 'SAME':
                        new_email = val
            
            return intent, new_name, new_email
        except Exception as e:
            print(f"[Calendly] ⚠️ Confirmation error: {e}", flush=True)
            return "confirm", name, email
    
    async def _complete_booking(self, name: str) -> None:
        """Complete the booking by clicking schedule button."""
        page = self.browser.page if self.browser else None
        if not page:
            await self._speak_and_save("I'm having trouble with the form. Could you click schedule manually?")
            return
        
        try:
            # Use JavaScript click to bypass overlay divs that intercept pointer events
            scheduled = await page.evaluate("""
                () => {
                    // Try Schedule Event button first
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = btn.textContent.trim().toLowerCase();
                        if (text.includes('schedule event') || 
                            text === 'schedule' ||
                            text === 'confirm' || 
                            text === 'book' ||
                            text === 'submit') {
                            btn.click();
                            return btn.textContent.trim();
                        }
                    }
                    
                    // Try submit button
                    const submitBtn = document.querySelector('button[type="submit"]');
                    if (submitBtn) {
                        submitBtn.click();
                        return 'submit';
                    }
                    
                    return null;
                }
            """)
            
            if scheduled:
                print(f"[Calendly] ✓ Clicked schedule button (JS): {scheduled}", flush=True)
                await asyncio.sleep(1.0)
                
                # Save user info to Firebase before clearing
                email = self.user_info.get('email', '')
                if self._save_user_info and name and email:
                    try:
                        await self._save_user_info(name, email)
                        print(f"[Calendly] ✓ Saved user info to Firebase: {name} ({email})", flush=True)
                    except Exception as e:
                        print(f"[Calendly] ⚠️ Failed to save user info: {e}", flush=True)
                
                self.on_calendly = False
                self.awaiting_confirmation = False
                self.user_info = {}
                await self._speak_and_save(f"You're all set, {name}! The meeting is booked. You'll receive a confirmation email shortly. It was great chatting with you!")
            else:
                print(f"[Calendly] ⚠️ No schedule button found", flush=True)
                await self._speak_and_save("Could you click the Schedule Event button to complete the booking?")
                
        except Exception as e:
            print(f"[Calendly] ⚠️ Failed to schedule: {e}", flush=True)
            await self._speak_and_save("Could you click the Schedule Event button to complete the booking?")

