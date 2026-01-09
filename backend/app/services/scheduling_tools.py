"""
Scheduling Tools - Tool definitions for VLM-based scheduling agent.

Defines the tools the VLM (Vision Language Model) can use to interact with
any scheduling page (Calendly, Cal.com, HubSpot, etc.) using screenshots.
"""

# OpenAI Function Calling tool definitions
SCHEDULING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click an element on the page. Use this to select dates, times, or buttons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element": {
                        "type": "string",
                        "description": "Description of the element to click (e.g., 'Thursday', '2:00pm', 'Schedule Event', 'Next')"
                    }
                },
                "required": ["element"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the page to see more content (more dates, times, etc.)",
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
            "name": "type_text",
            "description": "Type text into an input field on the page",
            "parameters": {
                "type": "object",
                "properties": {
                    "field_description": {
                        "type": "string",
                        "description": "Description of the field (e.g., 'name field', 'email input', 'Your name')"
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to type into the field"
                    }
                },
                "required": ["field_description", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "go_back",
            "description": "Go back to the previous page",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a question and wait for their response. Use this when you need information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user"
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Mark the scheduling as complete. Only use when booking is confirmed and you see a success/confirmation page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary message confirming the booking (e.g., 'Booked for Thursday at 2pm!')"
                    }
                },
                "required": ["summary"]
            }
        }
    }
]


def get_vlm_system_prompt(founder_name: str) -> str:
    """
    Generate the system prompt for the VLM-based visual scheduling agent.
    
    This prompt is used with screenshots - the VLM sees the screen visually.
    
    Args:
        founder_name: Name of the person being scheduled with
    """
    return f"""You are a visual scheduling assistant helping book a call with {founder_name}.

You will receive:
1. OVERARCHING GOAL - The big picture of what we're trying to accomplish
2. IMMEDIATE REQUEST - What the user just asked for RIGHT NOW

Focus on the IMMEDIATE REQUEST while keeping the OVERARCHING GOAL in mind.

NAVIGATION (use natural language descriptions):
- Future month: click "next month arrow" or "forward arrow button"
- Past month: click "previous month arrow" or "back arrow button"
- Select date: click the day number (e.g., "15" or "the 15th")
- Select time: click the time slot (e.g., "10:00" or "10:00 AM")
- Fill form: use type_text for name/email fields

IMPORTANT - BE SPECIFIC WITH ELEMENT DESCRIPTIONS:
When describing elements to click, be VERY SPECIFIC so they can be found uniquely:

- MONTH ARROWS (calendar navigation):
  - "next month arrow button" or "calendar forward arrow"
  - "previous month arrow button" or "calendar back arrow"
  
- BOOKING NEXT BUTTON (to proceed with booking):
  - "blue Next button next to time slots" 
  - "booking Next button on the right side"
  - NOT just "Next" or "Next button" - be specific!

- TIME SLOTS: Include the exact time, e.g., "10:00 time slot button"
- DATES: Include the day number, e.g., "day 15 button" or "the 15th"
- CONFIRM BUTTONS: "Schedule Event button" or "Confirm booking button"

BOOKING WORKFLOW:
1. Select a DATE (day number)
2. Select a TIME (time slot) - it will become highlighted/selected
3. Click "blue Next button next to time slots" to proceed - NOT the calendar arrows!
4. Fill in name/email if required
5. Click final confirm/schedule button

RULES:
1. Fulfill the IMMEDIATE REQUEST first
2. If user provides name/email, fill those fields in the form
3. If user provides date/time, navigate to and select it
4. Use ask_user ONLY when you need info you don't have
5. Use done ONLY when you see confirmation/success page
6. NEVER click the same element twice - if it's already selected/highlighted, move to the next step
7. If a time slot is highlighted/blue, it's already selected - click "Next" to proceed

CRITICAL:
- Use tool functions (click, scroll, type_text, go_back, ask_user, done)
- DO NOT write JSON - use actual tool calls
- Take ONE action per turn

SPEECH FORMAT:
- Keep it SHORT: 1-2 sentences max
- Do NOT list numbered observations or analysis
- Be conversational and natural

AFTER SUCCESSFUL NAVIGATION:
- NEVER say "You're already here" or "You're already viewing X"
- Instead say "Great, we're in [month] now!" or "Here we are in [month]!"
- Then ask what they want to do: "Which day works for you?"

Examples:
  - "Moving to March." (before action)
  - "Great, we're in March now! Which day looks good?" (after arriving)
  - "Selecting the 8th."
  - "Perfect, 10 AM is selected. Ready to proceed?"
  - "Filling in your details now."
  - "All set! Your call is booked.\""""


def get_info_extraction_prompt(user_message: str, current_info: dict) -> str:
    """
    Generate prompt to extract scheduling info from user message.
    
    Args:
        user_message: What the user said
        current_info: Currently collected info
    """
    return f"""Extract any scheduling-related information from the user's message.

USER MESSAGE: "{user_message}"

CURRENTLY KNOWN:
- date: {current_info.get('date') or 'unknown'}
- time: {current_info.get('time') or 'unknown'}
- name: {current_info.get('name') or 'unknown'}
- email: {current_info.get('email') or 'unknown'}

Extract any NEW information from the message. Look for:
- Dates: "Thursday", "tomorrow", "January 9", "next week", etc.
- Times: "2pm", "2:00", "afternoon", "morning", etc.
- Names: First name, full name
- Emails: Any email address

IMPORTANT FORMAT RULES:
- For dates: ALWAYS use NUMERIC day numbers, never spelled out
  - "March third" → "March 3"
  - "January tenth" → "January 10"
  - "the twenty-first" → "21"
- For times: Use format like "10 AM", "2 PM", "9:30 AM"

OUTPUT JSON:
{{
    "date": "Month Day (e.g., 'March 3', 'January 10') or null if not mentioned",
    "time": "Hour AM/PM (e.g., '10 AM', '2 PM') or null if not mentioned",
    "name": "extracted name or null if not mentioned",
    "email": "extracted email or null if not mentioned"
}}

Only output valid JSON, nothing else."""

