"""
AI Agent Service.
Orchestrates the voice AI pipeline: joins Daily calls, listens, thinks, speaks.

Pipeline: Daily Audio → Flux STT → Custom LLM → TTS → Daily Audio
"""

import asyncio
import re
import threading
from typing import Optional
from daily import Daily, CallClient, VirtualSpeakerDevice, VirtualMicrophoneDevice, EventHandler

from deepgram import AsyncDeepgramClient

# Initialize Daily SDK once at module load
_daily_initialized = False

def _ensure_daily_init():
    global _daily_initialized
    if not _daily_initialized:
        Daily.init()
        _daily_initialized = True
        print("[Daily] SDK initialized", flush=True)
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import ListenV2SocketClientResponse

from app.services.llm_service import LLMService
from app.services.tts_service import TTSService
from app.services.browser_service import browser_service, BrowserSession
from app.services.presenter_service import PresenterService
from app.services.planner_service import PlannerService, Plan
from app.services.demo_runner import DemoRunner, load_playbook, matches_trigger, is_demo_request, DemoState
from app.core.config import get_settings


class DailyEventHandler(EventHandler):
    """Event handler to monitor Daily call events."""
    
    def __init__(self, agent: 'AIAgent'):
        self.agent = agent
    
    def on_participant_joined(self, participant):
        pid = participant.get('id', 'unknown')
        info = participant.get('info', {})
        user_name = info.get('userName', '')
        is_local = participant.get('local', False)
        
        print(f"[Daily Event] Participant joined: {user_name} (id={pid[:8]}..., local={is_local})", flush=True)
        
        # Greet non-local (remote) participants who haven't been greeted yet
        if not is_local and user_name and pid not in self.agent.greeted_participants:
            self.agent.greeted_participants.add(pid)
            # Schedule greeting on the main event loop (callback runs in different thread)
            if self.agent._loop:
                asyncio.run_coroutine_threadsafe(
                    self.agent._greet_user(user_name),
                    self.agent._loop
                )
    
    def on_participant_updated(self, participant):
        """Monitor track state changes."""
        pid = participant.get('id', 'unknown')
        info = participant.get('info', {})
        user_name = info.get('userName', 'unknown')
        tracks = participant.get('media', {})
        
        # Get audio track info
        audio = tracks.get('microphone', {})
        audio_state = audio.get('state', 'unknown')
        audio_subscribed = audio.get('subscribed', False)
        
        print(f"[Daily Event] Participant updated: {user_name} (id={pid[:8]}...)", flush=True)
        print(f"[Daily Event]   Audio track: state={audio_state}, subscribed={audio_subscribed}", flush=True)
        print(f"[Daily Event]   Full media: {tracks}", flush=True)
    
    def on_participant_left(self, participant, reason):
        print(f"[Daily Event] Participant left: {participant.get('id', 'unknown')}", flush=True)


class AIAgent:
    """
    AI Agent that joins Daily calls and has voice conversations.
    
    Uses Flux STT for accurate turn detection, custom LLM for responses,
    and TTS for speech synthesis.
    """
    
    SAMPLE_RATE = 16000  # 16kHz for Flux
    
    def __init__(self, company_id: Optional[str] = None):
        settings = get_settings()
        
        # Company persona
        self.company_id = company_id
        
        # Services
        self.llm = LLMService()
        self.tts = TTSService()
        self.presenter = PresenterService(company_id=company_id)
        self.planner = PlannerService()
        self.deepgram = AsyncDeepgramClient(api_key=settings.deepgram_api_key)
        
        print(f"[Agent] Initialized with persona: {self.presenter.persona.name} ({self.presenter.persona.company})", flush=True)
        print(f"[Agent] Planner service ready", flush=True)
        
        # Daily client
        self.client: Optional[CallClient] = None
        self.speaker: Optional[VirtualSpeakerDevice] = None
        self.mic: Optional[VirtualMicrophoneDevice] = None
        
        # State
        self.is_running = False
        self.is_speaking = False
        self.room_url: str = ""
        self.room_name: str = ""
        self.token: str = ""
        self.greeted_participants: set = set()  # Track who we've greeted
        self.has_interacted: bool = False  # Track if user spoke first (skip greeting)
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # Store event loop for thread-safe scheduling
        self.pipeline_ready: bool = False  # True when audio pipeline is fully initialized
        self._demo_interrupted: bool = False  # True when user interrupts during a demo
        self._plan_interrupted: bool = False  # True when user interrupts during plan execution
        self._responding: bool = False  # True while in _respond() method
        self._awaiting_scheduling_confirmation: bool = False  # True when waiting for user to confirm scheduling
        self._on_calendly: bool = False  # True when on Calendly page for scheduling
        self._awaiting_calendly_info: bool = False  # True when waiting for name/email for Calendly
        self._awaiting_calendly_confirmation: bool = False  # True when waiting for user to confirm booking
        self._calendly_user_info: dict = {}  # Store name/email for confirmation
        
        # Browser session (if product demo)
        self.browser_session: Optional[BrowserSession] = None
        
        # Demo runner (for scripted playbooks)
        self.demo_runner: Optional[DemoRunner] = None
        if company_id:
            print(f"[Agent] Looking for playbook for: {company_id}", flush=True)
            self.playbook = load_playbook(company_id)
            if self.playbook:
                print(f"[Agent] 📚 Playbook loaded: {self.playbook.name} ({len(self.playbook.steps)} steps)", flush=True)
                print(f"[Agent] 📚 Triggers: {self.playbook.triggers}", flush=True)
            else:
                print(f"[Agent] ⚠️ No playbook found for {company_id}", flush=True)
        else:
            self.playbook = None
        
        # Transcript queue for async processing
        self._transcript_queue: asyncio.Queue = asyncio.Queue()
        
        # Deepgram connection
        self._dg_connection = None
        self._dg_task = None
    
    async def join_room(self, room_name: str, room_url: str, token: str) -> None:
        """Join a Daily room as an AI participant."""
        print(f"[Agent] Joining room: {room_url}", flush=True)
        
        self.room_name = room_name
        self.room_url = room_url
        self.token = token
        self.is_running = True
        self._loop = asyncio.get_running_loop()  # Capture event loop for thread-safe callbacks
        
        try:
            # Initialize Daily (only once)
            _ensure_daily_init()
            
            # Create virtual speaker to receive audio from participants
            self.speaker = Daily.create_speaker_device(
                "agent-speaker",
                sample_rate=self.SAMPLE_RATE,
                channels=1
            )
            Daily.select_speaker_device("agent-speaker")
            
            # Create virtual microphone to send TTS audio (publishes as regular mic track)
            self.mic = Daily.create_microphone_device(
                "agent-mic",
                sample_rate=self.SAMPLE_RATE,
                channels=1,
                non_blocking=False
            )
            print(f"[Agent] 🎤 Created VirtualMic: rate={self.mic.sample_rate}, ch={self.mic.channels}", flush=True)
            
            # Create call client with event handler
            self._event_handler = DailyEventHandler(self)
            self.client = CallClient(event_handler=self._event_handler)
            
            # Join the call
            join_event = threading.Event()
            join_error = [None]
            
            def on_joined(data, error):
                if error:
                    join_error[0] = error
                    print(f"[Agent] Failed to join: {error}", flush=True)
                else:
                    print("[Agent] ✓ Successfully joined the call!", flush=True)
                join_event.set()
            
            self.client.join(
                room_url,
                token,
                client_settings={
                    "inputs": {
                        "camera": False,
                        "microphone": {
                            "isEnabled": True,
                            "settings": {"deviceId": "agent-mic"}
                        }
                    },
                    "publishing": {
                        "camera": False,
                        "microphone": {"isPublishing": True}
                    }
                },
                completion=on_joined,
            )
            
            # Wait for join to complete
            join_event.wait(timeout=10)
            
            if join_error[0]:
                raise Exception(f"Failed to join: {join_error[0]}")
            
            # Set user name
            self.client.set_user_name("AI Assistant")
            
            # Small delay to let Daily threads stabilize after join
            await asyncio.sleep(0.5)
            
            # Force update inputs to ensure mic is active
            update_event = threading.Event()
            
            def on_inputs_updated(error):
                if error:
                    print(f"[Agent] ⚠️ Inputs update error: {error}", flush=True)
                else:
                    print("[Agent] 🎤 Microphone inputs updated!", flush=True)
                update_event.set()
            
            self.client.update_inputs({
                "microphone": {
                    "isEnabled": True,
                    "settings": {"deviceId": "agent-mic"}
                }
            }, completion=on_inputs_updated)
            update_event.wait(timeout=5)
            
            # Delay between updates to avoid race conditions in native code
            await asyncio.sleep(0.3)
            
            # Force update publishing
            pub_event = threading.Event()
            
            def on_pub_updated(error):
                if error:
                    print(f"[Agent] ⚠️ Publishing update error: {error}", flush=True)
                else:
                    print("[Agent] 📢 Microphone publishing enabled!", flush=True)
                pub_event.set()
            
            self.client.update_publishing({
                "microphone": {"isPublishing": True}
            }, completion=on_pub_updated)
            pub_event.wait(timeout=5)
            
            # Wait for WebRTC and Daily native threads to stabilize
            print("[Agent] Waiting for WebRTC to stabilize...", flush=True)
            await asyncio.sleep(2)
            
            # Subscribe to all participants' audio
            self.client.update_subscription_profiles({
                "base": {
                    "camera": "unsubscribed",
                    "microphone": "subscribed",
                }
            })
            
            # Now safe to initialize Firebase/memory (after Daily is stable)
            print("[Agent] Initializing conversation memory...", flush=True)
            await self.llm.set_room(room_name)
            
            # Check for browser session (product demo mode)
            self.browser_session = browser_service.get_session(room_name)
            if self.browser_session:
                print(f"[Agent] 🌐 Browser session found for product demo", flush=True)
                page_context = await self.browser_session.get_page_content()
                self.llm.set_browser_context(
                    page_context=page_context,
                    action_handlers={
                        "scroll_page": self._browser_scroll,
                        "click_element": self._browser_click,
                    }
                )
            
            # Another small delay before starting pipeline
            await asyncio.sleep(0.5)
            
            # Start the audio pipeline (no test tone)
            await self._start_pipeline()
            
        except Exception as e:
            print(f"[Agent] Error in join_room: {e}")
            import traceback
            traceback.print_exc()
            self.is_running = False
            raise
    
    async def _start_pipeline(self) -> None:
        """Start the audio processing pipeline."""
        print("[Agent] Starting audio pipeline...")
        
        # Connect to Deepgram Flux and start processing
        await self._run_with_flux()
    
    async def _run_deepgram_listener(self, connection) -> None:
        """Run the Deepgram websocket listener."""
        try:
            # start_listening is an async coroutine in v5 SDK
            await connection.start_listening()
        except Exception as e:
            print(f"[Agent] Deepgram listener error: {e}", flush=True)
    
    async def _run_with_flux(self) -> None:
        """Run the main loop with Flux STT connection."""
        print("[Agent] Connecting to Deepgram Flux...", flush=True)
        
        try:
            # Connect to Flux using v2 endpoint with async context manager
            async with self.deepgram.listen.v2.connect(
                model="flux-general-en",
                encoding="linear16",
                sample_rate=str(self.SAMPLE_RATE),
            ) as connection:
                
                print("[Agent] ✓ Connected to Deepgram Flux!", flush=True)
                self._dg_connection = connection
                
                # Set up event handlers
                def on_open(event):
                    print("[Agent] Flux WebSocket opened", flush=True)
                
                def on_message(message: ListenV2SocketClientResponse):
                    try:
                        msg_type = getattr(message, "type", "Unknown")
                        
                        # Handle transcription results
                        if hasattr(message, 'transcript') and message.transcript:
                            transcript = message.transcript.strip()
                            if transcript:
                                print(f"[Agent] 🎤 Heard: '{transcript}'", flush=True)
                                
                                # Mark that user has spoken (skip greeting if pending)
                                self.has_interacted = True
                                
                                # Mark plan as interrupted whenever user speaks during a response
                                # This catches interruptions during both speech AND thinking phases
                                if hasattr(self, '_responding') and self._responding:
                                    self._plan_interrupted = True
                                    print("[Agent] 🛑 User spoke during response - marking interrupted", flush=True)
                                
                                # Barge-in: stop AI if it's speaking
                                if self.is_speaking:
                                    print("[Agent] 🛑 Stopping speech", flush=True)
                                    self.is_speaking = False
                                    # If demo is running, mark it as interrupted
                                    if hasattr(self, '_demo_interrupted'):
                                        self._demo_interrupted = True
                                
                                # Put transcript in queue for processing
                                asyncio.create_task(self._transcript_queue.put(transcript))
                        
                        # Log other event types for debugging
                        elif msg_type == "Connected":
                            print("[Agent] ✓ Flux ready for audio!")
                        elif msg_type == "EndOfTurn":
                            print("[Agent] 🔄 End of turn detected")
                        elif msg_type == "EagerEndOfTurn":
                            print("[Agent] ⚡ Eager end of turn detected")
                            
                    except Exception as e:
                        print(f"[Agent] Error processing message: {e}")
                
                def on_close(event):
                    print("[Agent] Flux WebSocket closed")
                
                def on_error(error):
                    print(f"[Agent] Flux error: {error}")
                
                # Register event handlers
                connection.on(EventType.OPEN, on_open)
                connection.on(EventType.MESSAGE, on_message)
                connection.on(EventType.CLOSE, on_close)
                connection.on(EventType.ERROR, on_error)
                
                # Start listening - this runs the websocket receive loop
                # We need to run it concurrently with our audio loops
                self.pipeline_ready = True  # Signal that audio pipeline is ready for speech
                await asyncio.gather(
                    self._run_deepgram_listener(connection),
                    self._audio_receive_loop(),
                    self._transcript_process_loop(),
                )
                
        except Exception as e:
            print(f"[Agent] Failed to connect to Flux: {e}")
            import traceback
            traceback.print_exc()
    
    async def _audio_receive_loop(self) -> None:
        """Continuously receive audio from participants and send to Flux."""
        print("[Agent] Starting audio receive loop...")
        
        while self.is_running:
            try:
                if self.speaker and self._dg_connection:
                    # Read audio frames from the virtual speaker
                    # 2560 bytes = ~80ms at 16kHz (recommended chunk size for Flux)
                    audio_frames = self.speaker.read_frames(2560)
                    
                    if audio_frames and len(audio_frames) > 0:
                        # Send to Flux for transcription
                        await self._dg_connection._send(bytes(audio_frames))
                
                await asyncio.sleep(0.04)  # ~40ms delay (half chunk time)
                
            except Exception as e:
                if self.is_running:
                    print(f"[Agent] Audio receive error: {e}")
                await asyncio.sleep(0.1)
    
    async def _transcript_process_loop(self) -> None:
        """Process transcripts and generate responses."""
        print("[Agent] Starting transcript processing loop...")
        
        # Keep only the latest transcript (Flux sends cumulative partials)
        latest_transcript = ""
        last_transcript_time = asyncio.get_event_loop().time()
        
        while self.is_running:
            try:
                # Wait for a transcript with timeout
                try:
                    transcript = await asyncio.wait_for(
                        self._transcript_queue.get(),
                        timeout=0.3
                    )
                    # Replace with latest (Flux partials are cumulative, not diffs)
                    latest_transcript = transcript.strip()
                    last_transcript_time = asyncio.get_event_loop().time()
                    
                except asyncio.TimeoutError:
                    # Check if we should process the transcript
                    # (1 second of silence after last transcript)
                    current_time = asyncio.get_event_loop().time()
                    time_since_last = current_time - last_transcript_time
                    
                    if latest_transcript and time_since_last > 1.0 and not self.is_speaking:
                        # Process the final transcript
                        final_message = latest_transcript
                        latest_transcript = ""
                        
                        if len(final_message) > 2:  # Minimum length check
                            await self._respond(final_message)
                    
                    continue
                    
            except Exception as e:
                if self.is_running:
                    print(f"[Agent] Transcript processing error: {e}")
    
    async def _respond(self, user_message: str) -> None:
        """Generate and speak a response, potentially with browser actions."""
        self.is_speaking = True
        self._plan_interrupted = False  # Reset interruption flag for new response
        self._responding = True  # Track that we're in a response flow
        
        try:
            print(f"[Agent] 💬 Responding to: '{user_message}'")
            
            # === CHECK FOR SCHEDULING CONFIRMATION ===
            if self._awaiting_scheduling_confirmation:
                is_yes = await self._check_affirmative_response(user_message)
                if is_yes:
                    print(f"[Agent] 📅 User confirmed scheduling, opening Calendly", flush=True)
                    await self._open_calendly()
                    return
                else:
                    # User declined, just acknowledge
                    print(f"[Agent] 👋 User declined scheduling", flush=True)
                    self._awaiting_scheduling_confirmation = False
                    await self._speak("No problem at all! Feel free to reach out anytime. Take care!")
                    return
            
            # === CHECK FOR CALENDLY BOOKING CONFIRMATION ===
            if self._awaiting_calendly_confirmation and self.browser_session:
                print(f"[Agent] 📅 Processing Calendly confirmation", flush=True)
                await self._handle_calendly_confirmation(user_message)
                return
            
            # === CHECK FOR CALENDLY FORM FILLING ===
            if self._awaiting_calendly_info and self.browser_session:
                print(f"[Agent] 📅 Processing Calendly form info", flush=True)
                await self._fill_calendly_form(user_message)
                return
            
            # === CHECK FOR CALENDLY INTERACTION ===
            if self._on_calendly and self.browser_session:
                print(f"[Agent] 📅 On Calendly, handling scheduling interaction", flush=True)
                await self._handle_calendly_interaction(user_message)
                return
            
            # === CHECK FOR PLAYBOOK TRIGGER ===
            if self.playbook and self.browser_session:
                # Get conversation context for better demo detection
                from openai import AsyncOpenAI
                from app.core.config import get_settings
                settings = get_settings()
                client = AsyncOpenAI(api_key=settings.openai_api_key)
                
                # Get last AI message for context
                last_ai_message = ""
                if self.llm.memory:
                    history = self.llm.memory.get_messages_for_llm()
                    for msg in reversed(history):
                        if msg.get('role') == 'assistant':
                            last_ai_message = msg.get('content', '')[:200]
                            break
                
                # Use LLM to detect demo intent with context
                if await self._check_demo_intent(user_message, last_ai_message, client):
                    print(f"[Agent] 🎬 Playbook triggered: {self.playbook.name}", flush=True)
                    await self._run_playbook()
                    return
            
            # === CHECK FOR CLOSING INTENT ===
            closing_config = getattr(self.presenter.persona, 'closing', {})
            if closing_config:
                is_closing = await self._check_closing_intent(user_message)
                if is_closing:
                    print(f"[Agent] 👋 Closing intent detected", flush=True)
                    await self._handle_closing(closing_config)
                    return
            
            # Get current page context if we have a browser
            page_context = None
            available_actions = []
            if self.browser_session:
                try:
                    page_context = await self.browser_session.get_page_content()
                    self.presenter.update_page_context(page_context)
                    
                    # Extract clickable element texts for planner
                    clickables = page_context.get("clickable_elements", [])
                    available_actions = [el.get("text", "") for el in clickables if el.get("text")]
                except Exception as e:
                    print(f"[Agent] Could not update page context: {e}", flush=True)
            
            # Get conversation history from memory
            history = self.llm.memory.get_messages_for_llm() if self.llm.memory else []
            
            # Get site_map and home_url from persona for navigation
            site_map = self.presenter.persona.site_map if hasattr(self.presenter.persona, 'site_map') else []
            home_url = self.presenter.persona.home_url if hasattr(self.presenter.persona, 'home_url') else ''
            
            # Get page info
            current_url = page_context.get('url', '') if page_context else ''
            page_title = page_context.get('title', '') if page_context else ''
            page_text = page_context.get('text_content', '') if page_context else ''
            
            # === PHASE 1: CREATE NAVIGATION PLAN ===
            print(f"\n{'='*60}", flush=True)
            print(f"[Agent] 🗺️ PHASE 1: Creating navigation plan...", flush=True)
            print(f"[Agent] 📍 Current URL: {current_url}", flush=True)
            print(f"[Agent] 📍 Available elements: {available_actions[:5]}...", flush=True)
            
            # Build persona context for Planner to use in speech generation
            persona_context = {
                "name": self.presenter.persona.name,
                "tone": self.presenter.persona.tone,
                "speaking_style": self.presenter.persona.speaking_style,
                "product_name": self.presenter.persona.product_name,
            }
            
            # Detect current screen for context-aware responses (single LLM call)
            screen_context = await self._detect_current_screen(page_text)
            if screen_context:
                print(f"[Agent] 🖥️ Screen context: {screen_context.get('name', 'unknown')}", flush=True)
            
            # Derive home page status from screen detection (no extra LLM call!)
            is_on_home_page = screen_context and screen_context.get('id') == 'dashboard'
            print(f"[Agent] 🏠 On home page: {is_on_home_page}", flush=True)
            
            nav_plan = await self.planner.create_navigation_plan(
                user_message=user_message,
                current_url=current_url,
                page_title=page_title,
                site_map=site_map,
                available_elements=available_actions,
                home_url=home_url,
                persona_context=persona_context,
                is_on_home_page=is_on_home_page,
                conversation_history=history
            )
            
            # Check if there are any ACTION steps (click, navigate_to, navigate) in the plan
            plan_steps = nav_plan.get('plan', [])
            target_section_raw = nav_plan.get('target_section')
            target_section = (target_section_raw or '').lower()  # Handle None
            has_action_steps = any(
                step.get('action') in ['click', 'navigate_to', 'navigate'] 
                for step in plan_steps
            )
            
            # === NEW: Check if already on the target screen ===
            current_screen_id = screen_context.get('id', '').lower() if screen_context else ''
            already_on_target = False
            
            if current_screen_id and target_section:
                # Normalize both: remove underscores, spaces, hyphens for comparison
                def normalize(s: str) -> str:
                    return s.replace('_', '').replace(' ', '').replace('-', '').lower()
                
                current_normalized = normalize(current_screen_id)
                target_normalized = normalize(target_section)
                
                # Fuzzy match: check if normalized strings match or contain each other
                already_on_target = (
                    current_normalized == target_normalized or
                    current_normalized in target_normalized or 
                    target_normalized in current_normalized
                )
                
                if already_on_target and has_action_steps:
                    print(f"[Agent] 🎯 Already on target screen '{current_screen_id}' - skipping navigation!", flush=True)
                    has_action_steps = False  # Treat as "no navigation needed"
            
            # If no action steps, just respond (pure question)
            if not has_action_steps:
                print(f"[Agent] 💬 No actions in plan - just responding", flush=True)
                
                response_text = ""
                
                # If we skipped navigation because already on target, generate fresh response
                # (don't use Planner's pre-nav speech like "let me take you there")
                if already_on_target:
                    print(f"[Agent] 💬 Already on target - generating contextual response", flush=True)
                    response_text = await self.presenter.generate_response(
                        user_input=user_message,
                        conversation_history=history,
                        screen_context=screen_context
                    )
                else:
                    # 1. First, look for 'speak' step in the plan (Planner's generated speech)
                    for step in plan_steps:
                        if step.get('action') == 'speak' and step.get('details'):
                            response_text = step.get('details')
                            print(f"[Agent] 💬 Using Planner's speech from plan", flush=True)
                            break
                    
                    # 2. If no speak step, try speech_if_no_action field
                    if not response_text:
                        response_text = nav_plan.get('speech_if_no_action', '')
                        if response_text:
                            print(f"[Agent] 💬 Using speech_if_no_action field", flush=True)
                    
                    # 3. Last resort: generate with Presenter
                    if not response_text:
                        print(f"[Agent] 💬 Generating with Presenter (fallback)", flush=True)
                        response_text = await self.presenter.generate_response(
                            user_input=user_message,
                            conversation_history=history,
                            screen_context=screen_context
                        )
                
                await self._speak(response_text)
                if self.llm.memory:
                    await self.llm.memory.add_message("user", user_message)
                    await self.llm.memory.add_message("assistant", response_text)
                return
            
            # === PHASE 2: EXECUTE PLAN STEP BY STEP ===
            print(f"\n{'='*60}", flush=True)
            print(f"[Agent] 🚀 PHASE 2: Executing plan step-by-step...", flush=True)
            
            plan_steps = nav_plan.get('plan', [])
            target_section = nav_plan.get('target_section', '')
            first_speech_done = False
            final_speech = ""
            
            for step in plan_steps:
                # Check for interruption before each step
                if self._plan_interrupted:
                    print(f"[Agent] 🛑 Plan interrupted by user, stopping execution", flush=True)
                    break
                
                step_num = step.get('step', 0)
                step_action = step.get('action', '')
                step_details = step.get('details', '')
                
                print(f"\n[Agent] ▶️ Step {step_num}: {step_action} → {step_details}", flush=True)
                
                # Handle special actions
                if step_action == "done":
                    print(f"[Agent] ✅ Plan complete!", flush=True)
                    break
                
                if step_action == "speak":
                    if not first_speech_done:
                        await self._speak(step_details)
                        first_speech_done = True
                        final_speech = step_details
                    continue
                
                # Handle navigate action (direct URL navigation)
                if step_action == "navigate":
                    print(f"[Agent] 🌐 Navigating to: {step_details}", flush=True)
                    if self.browser_session:
                        success = await self.browser_session.navigate(step_details)
                        if success:
                            print(f"[Agent] ✅ Navigated to '{step_details}'", flush=True)
                            print(f"[Agent] ⏳ Waiting 2s for page to fully load...", flush=True)
                            await asyncio.sleep(0.3)  # Wait for page to load
                        else:
                            print(f"[Agent] ❌ Failed to navigate to '{step_details}'", flush=True)
                    continue
                
                # Handle direct click action from planner (clicks element by name)
                if step_action == "click":
                    # Wait a moment for page to be ready before clicking
                    await asyncio.sleep(0.3)
                    print(f"[Agent] 🖱️ Direct click: '{step_details}'", flush=True)
                    success = await self._browser_click(step_details)
                    if success:
                        print(f"[Agent] ✅ Clicked '{step_details}'", flush=True)
                        await asyncio.sleep(0.3)  # Wait for navigation after click
                    else:
                        print(f"[Agent] ❌ Failed to click '{step_details}'", flush=True)
                    continue
                
                # Get fresh page context before each action
                if self.browser_session:
                    await asyncio.sleep(0.3)  # Let page settle
                    page_context = await self.browser_session.get_page_content()
                    current_url = page_context.get('url', '')
                    page_title = page_context.get('title', '')
                    page_text = page_context.get('text_content', '')
                    clickables = page_context.get("clickable_elements", [])
                    available_actions = [el.get("text", "") for el in clickables if el.get("text")]
                    
                    print(f"[Agent] 📍 Now at: {current_url}", flush=True)
                    print(f"[Agent] 🔘 Elements: {available_actions[:5]}...", flush=True)
                
                # Execute the step
                execution = await self.planner.execute_plan_step(
                    plan_step=step,
                    target_section=target_section,
                    current_url=current_url,
                    page_title=page_title,
                    clickable_elements=available_actions,
                    page_text=page_text[:500]
                )
                
                action_type = execution.get('action_type', 'none')
                element = execution.get('element_to_click', '')
                nav_url = execution.get('url', '')
                
                print(f"[Agent] 🎯 Executing: {action_type} → {element or nav_url or 'N/A'}", flush=True)
                
                # Execute navigate action (direct URL)
                if action_type == "navigate" and nav_url:
                    print(f"[Agent] 🌐 Navigating to: {nav_url}", flush=True)
                    if self.browser_session:
                        success = await self.browser_session.navigate(nav_url)
                        if success:
                            print(f"[Agent] ✅ Navigated to '{nav_url}'", flush=True)
                            print(f"[Agent] ⏳ Waiting 2s for page to fully load...", flush=True)
                            await asyncio.sleep(0.3)  # Wait for page to load
                        else:
                            print(f"[Agent] ❌ Failed to navigate to '{nav_url}'", flush=True)
                    continue
                
                # Execute the action
                if action_type == "click" and element:
                    success = await self._browser_click(element)
                    if success:
                        print(f"[Agent] ✅ Clicked '{element}'", flush=True)
                        await asyncio.sleep(0.3)  # Wait for page to load
                    else:
                        print(f"[Agent] ❌ Failed to click '{element}'", flush=True)
                        # Try fallback
                        fallback = execution.get('fallback_action', 'none')
                        if fallback == "go_back":
                            await self.browser_session.page.go_back()
                            await asyncio.sleep(0.3)
                        elif fallback == "scroll_down":
                            await self.browser_session.scroll("down")
                            await asyncio.sleep(0.3)
                
                elif action_type == "go_back":
                    # Check if on dashboard - don't go back from there!
                    if "/dashboard" in current_url:
                        print(f"[Agent] ⚠️ On dashboard, can't go back (would go to login). Scrolling up instead.", flush=True)
                        await self.browser_session.scroll("up")
                        await asyncio.sleep(0.3)
                    else:
                        try:
                            await self.browser_session.page.go_back()
                            print(f"[Agent] ✅ Went back", flush=True)
                            await asyncio.sleep(0.3)
                        except Exception as e:
                            print(f"[Agent] ❌ Go back failed: {e}", flush=True)
                
                elif action_type == "scroll_up":
                    await self.browser_session.scroll("up")
                    print(f"[Agent] ✅ Scrolled up", flush=True)
                    await asyncio.sleep(0.3)
                
                elif action_type == "speak":
                    speech = execution.get('speech', step_details)
                    if speech and not first_speech_done:
                        await self._speak(speech)
                        first_speech_done = True
                        final_speech = speech
            
            # Final response if we haven't spoken yet
            if not first_speech_done and not self._plan_interrupted:
                # Refresh screen context after navigation
                if self.browser_session:
                    fresh_page = await self.browser_session.get_page_content()
                    fresh_text = fresh_page.get('text_content', '') if fresh_page else ''
                    screen_context = await self._detect_current_screen(fresh_text)
                
                # Generate a completion message (this is after navigation, so it's a continuation)
                final_speech = await self.presenter.generate_response(
                    user_input=user_message,
                    action_result=f"Navigated to {target_section}",
                    conversation_history=history,
                    screen_context=screen_context,
                    is_continuation=True  # We've navigated, now explain
                )
                await self._speak(final_speech)
            
            # === PHASE 3: POST-NAVIGATION RESPONSE ===
            # Skip if user interrupted
            if self._plan_interrupted:
                print(f"[Agent] 🛑 Skipping Phase 3 - user interrupted", flush=True)
            elif target_section and self.browser_session:
                print(f"\n[Agent] 💬 PHASE 3: Checking if explanation needed...", flush=True)
                
                # Get fresh page context after navigation
                await asyncio.sleep(0.3)
                page_context = await self.browser_session.get_page_content()
                self.presenter.update_page_context(page_context)
                page_text = page_context.get('text_content', '')[:800]
                
                # Refresh screen context for the new page
                screen_context = await self._detect_current_screen(page_text)
                if screen_context:
                    print(f"[Agent] 🖥️ New screen: {screen_context.get('name', 'unknown')}", flush=True)
                
                # Ask LLM if user needs a follow-up response
                follow_up = await self._check_needs_follow_up(
                    user_message=user_message,
                    target_section=target_section,
                    page_text=page_text
                )
                
                if follow_up and follow_up.get('needs_response'):
                    print(f"[Agent] 📝 LLM says: respond about '{follow_up.get('topic', target_section)}'", flush=True)
                    
                    # Generate contextual response as a CONTINUATION (not a fresh response)
                    explanation = await self.presenter.generate_response(
                        user_input=user_message,
                        action_result=f"Now showing the {target_section} section",
                        conversation_history=history,
                        screen_context=screen_context,
                        is_continuation=True  # Don't start with "Sure!" - we already acknowledged
                    )
                    
                    if explanation:
                        await self._speak(explanation)
                        final_speech = explanation  # Update for memory
                        print(f"[Agent] ✓ Explained {target_section}", flush=True)
                else:
                    # Always ask a follow-up question to keep conversation flowing
                    print(f"[Agent] 💬 No explanation needed, but asking follow-up question", flush=True)
                    screen_name = screen_context.get('name', target_section) if screen_context else target_section
                    follow_up_question = f"So here's the {screen_name}. Would you like me to walk you through how it works?"
                    await self._speak(follow_up_question)
                    final_speech = follow_up_question
                    print(f"[Agent] ✓ Asked follow-up about {target_section}", flush=True)
            
            print(f"\n{'='*60}", flush=True)
            print(f"[Agent] ✅ Navigation complete!", flush=True)
            
            # Save to memory
            if self.llm.memory and final_speech:
                await self.llm.memory.add_message("user", user_message)
                await self.llm.memory.add_message("assistant", final_speech)
                
        except Exception as e:
            print(f"[Agent] Error generating response: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.is_speaking = False
            self._responding = False  # Done with response flow
    
    async def _generate_speech(
        self, 
        user_message: str, 
        history: list, 
        plan: Plan,
        action_result: Optional[str] = None,
        screen_context: Optional[dict] = None,
        is_continuation: bool = False
    ) -> str:
        """Generate speech using the Presenter."""
        return await self.presenter.generate_response(
            user_input=user_message,
            action_result=action_result,
            conversation_history=history,
            screen_context=screen_context,
            is_continuation=is_continuation
        )
    
    async def _check_if_on_home_page(
        self,
        page_text: str,
        home_page_description: str
    ) -> bool:
        """
        Use LLM to determine if we're on the home page by comparing
        current page content to the home page description.
        
        Returns:
            bool: True if on home page, False otherwise
        """
        if not home_page_description:
            # No description provided, assume we're on home page
            return True
        
        from openai import AsyncOpenAI
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        prompt = f"""Compare the current page content to the home page description and determine if we're on the home page.

HOME PAGE DESCRIPTION:
{home_page_description}

CURRENT PAGE CONTENT:
{page_text[:1500]}

Question: Based on the content, is the user currently on the home page described above?

Answer with ONLY "yes" or "no" (lowercase, nothing else)."""

        try:
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0
            )
            
            answer = response.choices[0].message.content.strip().lower()
            is_home = answer == "yes"
            
            print(f"[Agent] 🏠 LLM home check: '{answer}' → {is_home}", flush=True)
            return is_home
            
        except Exception as e:
            print(f"[Agent] ⚠️ Home page check failed: {e}", flush=True)
            # On error, assume we're on home page to avoid unnecessary navigation
            return True
    
    async def _check_needs_follow_up(
        self, 
        user_message: str, 
        target_section: str,
        page_text: str
    ) -> dict:
        """
        Ask LLM if the user's message needs a follow-up explanation after navigation.
        
        Returns:
            dict with 'needs_response' (bool) and 'topic' (str)
        """
        from openai import AsyncOpenAI
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
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
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            import json
            result = json.loads(response.choices[0].message.content or "{}")
            return result
            
        except Exception as e:
            print(f"[Agent] Follow-up check error: {e}", flush=True)
            return {"needs_response": False}
    
    async def _check_closing_intent(self, user_message: str) -> bool:
        """
        Use LLM to detect if user is signaling they're done with the demo/conversation.
        Examples: "all good", "that's all", "I've seen enough", "no thanks", "I'm good"
        """
        from openai import AsyncOpenAI
        from app.core.config import get_settings
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        # Get conversation history for context
        all_history = self.llm.memory.get_messages_for_llm() if self.llm.memory else []
        history = all_history[-4:] if all_history else []
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
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0
            )
            
            answer = response.choices[0].message.content.strip().lower()
            is_closing = answer == "yes"
            print(f"[Agent] 👋 Closing intent check: '{user_message[:30]}...' → {is_closing}", flush=True)
            return is_closing
            
        except Exception as e:
            print(f"[Agent] Closing intent check error: {e}", flush=True)
            return False
    
    async def _check_demo_intent(self, user_message: str, last_ai_message: str, client) -> bool:
        """Check if user wants a demo/tour using LLM with conversation context."""
        prompt = f"""Determine if the user wants a product demo or tour.

LAST AI MESSAGE: "{last_ai_message}"
USER'S RESPONSE: "{user_message}"

The user wants a demo if:
- They explicitly ask for a demo, tour, or walkthrough
- They say "yes", "sure", "I'd love to" etc. in response to an offer for a demo/tour
- They ask to see features or how things work

Answer ONLY "yes" or "no"."""

        try:
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0
            )
            answer = response.choices[0].message.content.strip().lower()
            print(f"[Agent] 🎬 Demo intent check: '{user_message[:30]}...' (after: '{last_ai_message[:30]}...') → {answer}", flush=True)
            return answer == "yes"
        except Exception as e:
            print(f"[Agent] ⚠️ Error checking demo intent: {e}", flush=True)
            return False
    
    async def _handle_closing(self, closing_config: dict) -> None:
        """Handle the closing flow - say goodbye and offer to schedule a call."""
        founder_name = closing_config.get('founder_name', 'the founder')
        closing_message = closing_config.get('closing_message', '')
        
        if not closing_message:
            closing_message = f"It was such a pleasure showing you around! If you'd like to chat more, I can set up a quick call with {founder_name}. Would you like me to schedule that for you?"
        
        # Replace placeholders
        closing_message = closing_message.replace('{founder_name}', founder_name)
        
        print(f"[Agent] 👋 Speaking closing message", flush=True)
        await self._speak(closing_message)
        
        # Set flag to wait for scheduling confirmation
        self._awaiting_scheduling_confirmation = True
        
        # Save to memory
        if self.llm.memory:
            await self.llm.memory.add_message("assistant", closing_message)
    
    async def _check_affirmative_response(self, user_message: str) -> bool:
        """Check if user's response is affirmative using LLM."""
        from openai import AsyncOpenAI
        from app.core.config import get_settings
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        prompt = f"""The AI just asked the user if they'd like to schedule a call with the founder.

User's response: "{user_message}"

Is this an affirmative response (yes, they want to schedule)?

Respond with ONLY "yes" or "no"."""

        try:
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0
            )
            answer = response.choices[0].message.content.strip().lower()
            print(f"[Agent] 🤔 Affirmative check: '{user_message}' -> {answer}", flush=True)
            return answer == "yes"
        except Exception as e:
            print(f"[Agent] ⚠️ Error checking affirmative: {e}", flush=True)
            return False
    
    async def _open_calendly(self) -> None:
        """Open Calendly link in browser and speak scheduling message."""
        self._awaiting_scheduling_confirmation = False
        
        closing_config = getattr(self.presenter.persona, 'closing', {})
        calendly_url = closing_config.get('calendly_url', '')
        scheduling_message = closing_config.get('scheduling_message', 
            "I'm opening up the calendar now. Take a look and let me know what time works best for you!")
        
        if calendly_url and self.browser_session:
            print(f"[Agent] 📅 Opening Calendly: {calendly_url}", flush=True)
            await self._speak(scheduling_message)
            await self.browser_session.navigate(calendly_url)
            await asyncio.sleep(1.0)  # Wait for Calendly to load
            self._on_calendly = True
            print(f"[Agent] ✓ Calendly opened, ready for scheduling", flush=True)
        else:
            await self._speak("I'd love to help you schedule, but I don't have the calendar link handy. You can reach out directly to schedule a call!")
        
        # Save to memory
        if self.llm.memory:
            await self.llm.memory.add_message("assistant", scheduling_message)
    
    async def _handle_calendly_interaction(self, user_message: str) -> None:
        """Handle user interactions on Calendly page (day/time selection)."""
        from openai import AsyncOpenAI
        from app.core.config import get_settings
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        # Get current page content to find clickable elements
        page = self.browser_session.page
        if not page:
            await self._speak("I'm having trouble with the calendar. Could you try again?")
            return
        
        # Check if user wants to go back/scroll/select using LLM
        try:
            prompt = f"""The user is on a Calendly scheduling page. They said: "{user_message}"

What is the user's intent?
- "select" = They mention a SPECIFIC date (like "January 5th", "the 12th", "Monday") OR a specific time (like "10am", "2:30")
- "scroll" = They want to scroll to see more times (like "scroll down", "show more", "see other times")
- "back" = They want to go back to the previous page, exit scheduling, or cancel

IMPORTANT: If they mention ANY specific date or time, answer "select".

Answer ONLY one word: "back", "scroll", or "select"."""
            
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0
            )
            intent = response.choices[0].message.content.strip().lower()
            print(f"[Agent] 📅 Calendly intent: {intent}", flush=True)
            
            if intent == "scroll":
                print(f"[Agent] 📅 User wants to scroll on Calendly", flush=True)
                try:
                    # Debug: Print scrollable elements
                    scrollable_info = await page.evaluate("""
                        () => {
                            const results = [];
                            const allElements = document.querySelectorAll('*');
                            for (const el of allElements) {
                                if (el.scrollHeight > el.clientHeight && el.clientHeight > 50) {
                                    results.push({
                                        tag: el.tagName,
                                        class: el.className.substring(0, 100),
                                        id: el.id,
                                        scrollHeight: el.scrollHeight,
                                        clientHeight: el.clientHeight,
                                        overflow: getComputedStyle(el).overflow
                                    });
                                }
                            }
                            return results.slice(0, 10);  // Limit to 10
                        }
                    """)
                    print(f"[Agent] 📜 Scrollable elements found:", flush=True)
                    for el in scrollable_info:
                        print(f"  - {el['tag']} class='{el['class'][:50]}' id='{el['id']}' scroll={el['scrollHeight']} client={el['clientHeight']} overflow={el['overflow']}", flush=True)
                    # Target the Calendly time slots container directly (booking-kit_spotlist-list)
                    scrolled = await page.evaluate("""
                        () => {
                            // Look for the booking-kit spotlist container (Calendly's time slots)
                            const spotlist = document.querySelector('[class*="spotlist-list"]') ||
                                            document.querySelector('[class*="booking-kit_spotlist"]');
                            if (spotlist && spotlist.scrollHeight > spotlist.clientHeight) {
                                spotlist.scrollBy(0, 200);
                                return 'spotlist';
                            }
                            
                            // Fallback: find any div with overflow:auto and scrollable
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
                        print(f"[Agent] ✓ Scrolled using {scrolled}", flush=True)
                    else:
                        print(f"[Agent] ⚠️ No scrollable container found", flush=True)
                    
                    await asyncio.sleep(0.3)
                    await self._speak("Here you go! Let me know which time works for you.")
                    return
                except Exception as e:
                    print(f"[Agent] ⚠️ Could not scroll: {e}", flush=True)
                    await self._speak("I'm having trouble scrolling. You can scroll manually to see more times.")
                    return
            
            if intent == "back":
                print(f"[Agent] 📅 User wants to go back on Calendly", flush=True)
                # Try clicking back button or using browser back
                try:
                    back_clicked = False
                    for selector in ['button:has-text("Back")', 'button:has-text("←")', '[aria-label*="back" i]', '[aria-label*="previous" i]']:
                        try:
                            await page.click(selector, timeout=1000)
                            back_clicked = True
                            print(f"[Agent] ✓ Clicked back button", flush=True)
                            break
                        except:
                            continue
                    
                    if not back_clicked:
                        # Use browser back
                        await page.go_back()
                        print(f"[Agent] ✓ Used browser back", flush=True)
                    
                    await asyncio.sleep(0.5)
                    self._awaiting_calendly_info = False
                    await self._speak("No problem! Here's the calendar again. Which date works better for you?")
                    return
                except Exception as e:
                    print(f"[Agent] ⚠️ Could not go back: {e}", flush=True)
        except Exception as e:
            print(f"[Agent] ⚠️ Error checking calendly intent: {e}", flush=True)
        
        # Extract clickable elements from Calendly
        clickable_elements = await page.evaluate("""
            () => {
                const elements = [];
                
                // Find ALL buttons in the calendar - Calendly uses buttons for dates
                document.querySelectorAll('button').forEach(el => {
                    const text = el.textContent.trim();
                    const ariaLabel = el.getAttribute('aria-label') || '';
                    const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                    
                    // Skip if disabled or empty
                    if (disabled || !text) return;
                    
                    // Date buttons - usually just numbers 1-31
                    if (/^\\d{1,2}$/.test(text)) {
                        elements.push({type: 'date', text: text, ariaLabel: ariaLabel});
                    }
                    // Time slots - contain : or am/pm
                    else if (text.match(/\\d{1,2}:\\d{2}/) || text.match(/\\d{1,2}\\s*(am|pm|AM|PM)/)) {
                        elements.push({type: 'time', text: text});
                    }
                    // Action buttons
                    else if (text.toLowerCase().includes('next') || 
                             text.toLowerCase().includes('confirm') || 
                             text.toLowerCase().includes('schedule')) {
                        elements.push({type: 'action', text: text});
                    }
                });
                
                // Also check for clickable table cells (some calendar implementations)
                document.querySelectorAll('td[role="button"], td[tabindex="0"], [role="gridcell"] button').forEach(el => {
                    const text = el.textContent.trim();
                    if (/^\\d{1,2}$/.test(text) && !el.getAttribute('aria-disabled')) {
                        elements.push({type: 'date', text: text, ariaLabel: el.getAttribute('aria-label') || ''});
                    }
                });
                
                return elements;
            }
        """)
        
        print(f"[Agent] 📅 Calendly elements found: {clickable_elements[:10]}...", flush=True)
        
        # Use LLM to determine what to click
        prompt = f"""The user is on a Calendly scheduling page. They said: "{user_message}"

Available clickable elements on the page:
{clickable_elements}

What should I click?

RULES:
- For DATES (like "January 5th", "the 5th") → respond with just the number: "5"
- For TIMES (like "5am", "10:30am", "2pm") → respond with EXACT time text from the list: "5:00am" or "10:30am"
- For confirm/next → respond with "Next" or "Confirm"

IMPORTANT: If user says a TIME like "5am", find the matching time in the list (e.g., "5:00am") - do NOT respond with just "5"!

Respond with ONLY the exact text to click. If nothing matches, respond "NONE"."""

        try:
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0
            )
            target_text = response.choices[0].message.content.strip()
            print(f"[Agent] 📅 LLM says click: '{target_text}'", flush=True)
            
            if target_text == "NONE" or not target_text:
                await self._speak("I couldn't find that on the calendar. Could you try saying the day or time again?")
                return
            
            # Try to click the element - use Playwright locator (most reliable)
            clicked = False
            try:
                await page.locator(f'button:has-text("{target_text}")').first.click(timeout=500)
                clicked = True
                print(f"[Agent] ✓ Clicked: '{target_text}'", flush=True)
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
                    clicked = True
                    print(f"[Agent] ✓ Clicked (JS): '{target_text}'", flush=True)
                except:
                    pass
            
            if clicked:
                await asyncio.sleep(0.5)  # Brief wait for UI
                
                # Check if we clicked a time (need to click Next)
                if any(c in target_text.lower() for c in ['am', 'pm', ':']):
                    await asyncio.sleep(0.8)  # Wait for Next button to appear
                    
                    # Click Next button using JS (most reliable for Calendly)
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
                        print(f"[Agent] ✓ Clicked Next button", flush=True)
                        await asyncio.sleep(0.5)  # Wait for form
                        self._awaiting_calendly_info = True
                        await self._speak("Got it! What's your name and email so I can confirm the booking?")
                    else:
                        print(f"[Agent] ⚠️ Next button not found", flush=True)
                        await self._speak("I selected the time. Could you click Next to continue?")
                else:
                    await self._speak("Perfect! Now which time slot works for you?")
            else:
                await self._speak("I couldn't click that. Could you try saying it differently?")
                print(f"[Agent] ⚠️ Failed to click: '{target_text}'", flush=True)
                
        except Exception as e:
            print(f"[Agent] ⚠️ Calendly interaction error: {e}", flush=True)
            await self._speak("I'm having trouble with the calendar. Could you try again?")
    
    async def _fill_calendly_form(self, user_message: str) -> None:
        """Fill in the Calendly booking form with user's name and email."""
        from openai import AsyncOpenAI
        from app.core.config import get_settings
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        # First check if user wants to change date/time instead of providing info
        intent_prompt = f"""The user was asked for their name and email to book a meeting. They said: "{user_message}"

What is their intent?
- "change_time" = They want to go back and pick a different date or time (mentions a day, date, or wants to change)
- "provide_info" = They are providing their name and/or email

Answer ONLY: "change_time" or "provide_info"."""

        try:
            intent_response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": intent_prompt}],
                max_tokens=20,
                temperature=0
            )
            intent = intent_response.choices[0].message.content.strip().lower()
            print(f"[Agent] 📅 Form intent: {intent}", flush=True)
            
            if intent == "change_time":
                # User wants to go back to calendar
                print(f"[Agent] 📅 User wants to change date/time, going back", flush=True)
                self._awaiting_calendly_info = False
                page = self.browser_session.page
                if page:
                    try:
                        # Click back or use browser back
                        back_clicked = False
                        for selector in ['button:has-text("Back")', '[aria-label*="back" i]']:
                            try:
                                await page.click(selector, timeout=1000)
                                back_clicked = True
                                break
                            except:
                                continue
                        if not back_clicked:
                            await page.go_back()
                        await asyncio.sleep(0.5)
                    except:
                        pass
                
                # Now handle as a calendar interaction
                await self._handle_calendly_interaction(user_message)
                return
        except Exception as e:
            print(f"[Agent] ⚠️ Error checking form intent: {e}", flush=True)
        
        # Use LLM to extract name and email from user's message
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
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0
            )
            result = response.choices[0].message.content.strip()
            print(f"[Agent] 📅 Extracted info: {result}", flush=True)
            
            # Parse the result
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
            
            # Check what we're missing
            if not name and not email:
                await self._speak("I didn't catch that. Could you tell me your name and email?")
                return
            elif not name:
                await self._speak(f"Got your email. What's your name?")
                return
            elif not email:
                await self._speak(f"Thanks {name}! What's your email address?")
                return
            
            # We have both - fill the form
            page = self.browser_session.page
            if not page:
                await self._speak("I'm having trouble with the form. Could you try again?")
                return
            
            print(f"[Agent] 📅 Filling form - Name: {name}, Email: {email}", flush=True)
            
            # Fill name field
            try:
                # Try common Calendly name field selectors
                name_filled = False
                for selector in ['input[name="full_name"]', 'input[name="name"]', 'input[placeholder*="name" i]', 'input[aria-label*="name" i]']:
                    try:
                        await page.locator(selector).first.fill(name, timeout=1000)
                        name_filled = True
                        print(f"[Agent] ✓ Filled name with selector: {selector}", flush=True)
                        break
                    except:
                        continue
                
                if not name_filled:
                    # Fallback: find first visible text input
                    await page.locator('input[type="text"]').first.fill(name, timeout=2000)
                    print(f"[Agent] ✓ Filled name (fallback)", flush=True)
            except Exception as e:
                print(f"[Agent] ⚠️ Failed to fill name: {e}", flush=True)
            
            # Fill email field
            try:
                email_filled = False
                for selector in ['input[name="email"]', 'input[type="email"]', 'input[placeholder*="email" i]', 'input[aria-label*="email" i]']:
                    try:
                        await page.locator(selector).first.fill(email, timeout=1000)
                        email_filled = True
                        print(f"[Agent] ✓ Filled email with selector: {selector}", flush=True)
                        break
                    except:
                        continue
                
                if not email_filled:
                    print(f"[Agent] ⚠️ Could not find email field", flush=True)
            except Exception as e:
                print(f"[Agent] ⚠️ Failed to fill email: {e}", flush=True)
            
            await asyncio.sleep(0.3)
            
            # Store the info and ask for confirmation before scheduling
            self._calendly_user_info = {'name': name, 'email': email}
            self._awaiting_calendly_info = False
            self._awaiting_calendly_confirmation = True
            
            await self._speak(f"I've filled in {name} with email {email}. Does that look correct? Say yes to confirm or let me know what to change.")
                
        except Exception as e:
            print(f"[Agent] ⚠️ Calendly form error: {e}", flush=True)
            await self._speak("I'm having trouble with the form. Could you try again?")
    
    async def _handle_calendly_confirmation(self, user_message: str) -> None:
        """Handle user's confirmation or correction of Calendly booking info."""
        from openai import AsyncOpenAI
        from app.core.config import get_settings
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        name = self._calendly_user_info.get('name', '')
        email = self._calendly_user_info.get('email', '')
        
        # Use LLM to determine if this is confirmation or correction
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
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0
            )
            result = response.choices[0].message.content.strip()
            print(f"[Agent] 📅 Confirmation response: {result}", flush=True)
            
            # Parse response
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
            
            if intent == "cancel":
                self._awaiting_calendly_confirmation = False
                self._on_calendly = False
                await self._speak("No problem, we can skip the scheduling for now. Is there anything else I can help you with?")
                return
            
            if intent in ["change_name", "change_email", "change_both"]:
                # Update stored info
                self._calendly_user_info = {'name': new_name, 'email': new_email}
                
                # Refill the form
                page = self.browser_session.page
                if page:
                    if intent in ["change_name", "change_both"]:
                        try:
                            for selector in ['input[name="full_name"]', 'input[name="name"]', 'input[placeholder*="name" i]', 'input[type="text"]']:
                                try:
                                    await page.locator(selector).first.fill(new_name, timeout=1000)
                                    print(f"[Agent] ✓ Updated name to: {new_name}", flush=True)
                                    break
                                except:
                                    continue
                        except Exception as e:
                            print(f"[Agent] ⚠️ Failed to update name: {e}", flush=True)
                    
                    if intent in ["change_email", "change_both"]:
                        try:
                            for selector in ['input[name="email"]', 'input[type="email"]', 'input[placeholder*="email" i]']:
                                try:
                                    await page.locator(selector).first.fill(new_email, timeout=1000)
                                    print(f"[Agent] ✓ Updated email to: {new_email}", flush=True)
                                    break
                                except:
                                    continue
                        except Exception as e:
                            print(f"[Agent] ⚠️ Failed to update email: {e}", flush=True)
                
                await self._speak(f"Updated! Now showing {new_name} with email {new_email}. Does that look right?")
                return
            
            # Intent is confirm - click the schedule button
            page = self.browser_session.page
            if not page:
                await self._speak("I'm having trouble with the form. Could you click schedule manually?")
                return
            
            try:
                scheduled = False
                for btn_text in ['Schedule Event', 'Confirm', 'Book', 'Submit']:
                    try:
                        await page.get_by_role("button", name=btn_text).first.click(timeout=1000)
                        scheduled = True
                        print(f"[Agent] ✓ Clicked schedule button: {btn_text}", flush=True)
                        break
                    except:
                        continue
                
                if not scheduled:
                    await page.locator('button[type="submit"]').first.click(timeout=2000)
                    scheduled = True
                    print(f"[Agent] ✓ Clicked submit button", flush=True)
                
                if scheduled:
                    await asyncio.sleep(1.0)
                    self._on_calendly = False
                    self._awaiting_calendly_confirmation = False
                    self._calendly_user_info = {}
                    await self._speak(f"You're all set, {name}! The meeting is booked. You'll receive a confirmation email shortly. It was great chatting with you!")
                else:
                    await self._speak("Could you click the Schedule Event button to complete the booking?")
                    
            except Exception as e:
                print(f"[Agent] ⚠️ Failed to schedule: {e}", flush=True)
                await self._speak("Could you click the Schedule Event button to complete the booking?")
                
        except Exception as e:
            print(f"[Agent] ⚠️ Confirmation error: {e}", flush=True)
            await self._speak("I didn't catch that. Should I go ahead and schedule, or would you like to change something?")
    
    async def _detect_current_screen(self, page_text: str) -> Optional[dict]:
        """
        Use LLM to detect which screen the user is currently on by matching
        page content against the persona's screen descriptions.
        
        Returns:
            dict with screen info (id, name, description, purpose, key_actions) or None
        """
        # Get screens from persona
        screens = getattr(self.presenter.persona, 'screens', {})
        if not screens:
            print("[Agent] No screens defined in persona, skipping screen detection", flush=True)
            return None
        
        # Build screen descriptions for LLM
        screen_descriptions = []
        for screen_id, screen_info in screens.items():
            name = screen_info.get('name', screen_id)
            desc = screen_info.get('description', '')
            screen_descriptions.append(f"- {screen_id}: {name}\n  {desc[:200]}...")
        
        from openai import AsyncOpenAI
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        prompt = f"""Based on the current page content, determine which screen the user is viewing.

AVAILABLE SCREENS:
{chr(10).join(screen_descriptions)}

CURRENT PAGE CONTENT:
{page_text[:1500]}

Which screen ID best matches the current page content?
Answer with ONLY the screen ID (e.g., "dashboard", "journaling", "meditation") or "unknown" if none match."""

        try:
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
                temperature=0.0
            )
            
            screen_id = response.choices[0].message.content.strip().lower()
            print(f"[Agent] 🖥️ Detected screen: '{screen_id}'", flush=True)
            
            if screen_id in screens:
                screen_info = screens[screen_id]
                return {
                    "id": screen_id,
                    "name": screen_info.get('name', screen_id),
                    "description": screen_info.get('description', ''),
                    "purpose": screen_info.get('purpose', ''),
                    "key_actions": screen_info.get('key_actions', [])
                }
            else:
                print(f"[Agent] Screen '{screen_id}' not found in persona screens", flush=True)
                return None
                
        except Exception as e:
            print(f"[Agent] ⚠️ Screen detection failed: {e}", flush=True)
            return None
    
    async def _greet_user(self, user_name: str) -> None:
        """Greet a user when they join the call."""
        # Wait for audio pipeline to be ready (Deepgram connected, loops running)
        max_wait = 10  # Max 10 seconds
        waited = 0
        while not self.pipeline_ready and waited < max_wait:
            await asyncio.sleep(0.5)
            waited += 0.5
        
        if not self.pipeline_ready:
            print(f"[Agent] Skipping greeting - pipeline not ready after {max_wait}s", flush=True)
            return
        
        # Wait a moment for user to settle in after pipeline is ready
        await asyncio.sleep(1.0)
        
        # Don't greet if we're not running
        if not self.is_running:
            print(f"[Agent] Skipping greeting - agent not running", flush=True)
            return
        
        # Don't greet if user already spoke first
        if self.has_interacted:
            print(f"[Agent] Skipping greeting - user already initiated conversation", flush=True)
            return
        
        # Get greeting template from persona
        greeting_template = getattr(self.presenter.persona, 'greeting_template', '')
        if not greeting_template:
            greeting_template = "Hey {user_name}, nice to meet you! Ready for a quick tour?"
        
        # Fill in the user's name
        greeting = greeting_template.replace('{user_name}', user_name)
        
        print(f"[Agent] 👋 Greeting user: {user_name}", flush=True)
        print(f"[Agent] 💬 Saying: {greeting}", flush=True)
        
        # Speak the greeting
        await self._speak(greeting)
    
    async def _speak(self, text: str) -> None:
        """Convert text to speech and play it."""
        if not text:
            return
            
        audio_data = await self.tts.synthesize(text)
        print(f"[Agent] 🔊 Generated {len(audio_data)} bytes of audio", flush=True)
        
        if self.mic and audio_data:
            print(f"[Agent] 📤 Streaming {len(audio_data)} bytes...", flush=True)
            self.is_speaking = True  # Mark as speaking BEFORE streaming
            
            def write_audio_sync():
                """Write audio - blocking mic handles pacing internally."""
                chunk_ms = 100
                samples_per_chunk = int(self.SAMPLE_RATE * (chunk_ms / 1000.0))
                chunk_bytes = samples_per_chunk * 2
                
                chunks_sent = 0
                interrupted = False
                for i in range(0, len(audio_data), chunk_bytes):
                    if not self.is_speaking or not self.is_running:
                        interrupted = True
                        break
                    chunk = audio_data[i:i + chunk_bytes]
                    try:
                        self.mic.write_frames(chunk)
                        chunks_sent += 1
                    except Exception as e:
                        print(f"[Agent] ❌ Audio write error: {e}", flush=True)
                        break
                return (chunks_sent, interrupted)
            
            chunks_sent, interrupted = await asyncio.to_thread(write_audio_sync)
            self.is_speaking = False  # Done speaking
            if interrupted:
                print(f"[Agent] ⏹️ Speech interrupted after {chunks_sent} chunks", flush=True)
            else:
                print(f"[Agent] ✓ Finished speaking ({chunks_sent} chunks)", flush=True)
        else:
            print(f"[Agent] ⚠️ Cannot send audio: mic={self.mic is not None}", flush=True)
    
    async def _execute_actions(self, plan: Plan) -> None:
        """Execute all actions from the plan (supports multi-step navigation)."""
        if not self.browser_session:
            return
        
        # Get actions list (or single action for backwards compat)
        actions = plan.actions if plan.actions else ([plan.action] if plan.action else [])
        
        if not actions:
            return
        
        print(f"[Agent] 🚀 Executing {len(actions)} action(s)...", flush=True)
        
        for i, action in enumerate(actions):
            print(f"[Agent] 🎯 Step {i+1}/{len(actions)}: {action.action_type} → {action.target}", flush=True)
            
            try:
                if action.action_type == "scroll":
                    direction = action.target or "down"
                    await self.browser_session.scroll(direction)
                    print(f"[Agent] ✓ Scrolled {direction}", flush=True)
                    
                elif action.action_type == "click":
                    if action.target:
                        success = await self._browser_click(action.target)
                        if not success:
                            print(f"[Agent] ⚠️ Click may have failed, continuing...", flush=True)
                        else:
                            # Wait for page to update after successful click
                            await asyncio.sleep(0.3)
                        
                elif action.action_type == "navigate":
                    if action.target:
                        await self.browser_session.navigate(action.target)
                        print(f"[Agent] ✓ Navigated to {action.target}", flush=True)
                        
                elif action.action_type == "go_back":
                    try:
                        await self.browser_session.page.go_back()
                        print(f"[Agent] ✓ Went back", flush=True)
                    except Exception as e:
                        print(f"[Agent] ⚠️ Go back failed: {e}", flush=True)
                        
                elif action.action_type == "wait":
                    await asyncio.sleep(1)
                    print(f"[Agent] ✓ Waited", flush=True)
                
                # Small delay between actions for page to update
                if i < len(actions) - 1:
                    await asyncio.sleep(0.3)
                    
            except Exception as e:
                print(f"[Agent] ❌ Action {i+1} failed: {e}", flush=True)
    
    async def _execute_action(self, plan: Plan) -> None:
        """Execute a single action (backwards compat wrapper)."""
        await self._execute_actions(plan)
    
    async def _execute_single_action(self, action) -> bool:
        """Execute a single BrowserAction object. Returns success/failure."""
        if not self.browser_session or not action:
            return False
        
        print(f"[Agent] 🎯 Action: {action.action_type} → {action.target}", flush=True)
        
        try:
            if action.action_type == "scroll":
                direction = action.target or "down"
                await self.browser_session.scroll(direction)
                print(f"[Agent] ✓ Scrolled {direction}", flush=True)
                return True
                
            elif action.action_type == "click":
                if action.target:
                    success = await self._browser_click(action.target)
                    if success:
                        print(f"[Agent] ✓ Clicked successfully", flush=True)
                        await asyncio.sleep(0.3)  # Wait for page update
                    else:
                        print(f"[Agent] ⚠️ Click may have failed", flush=True)
                    return success
                    
            elif action.action_type == "navigate":
                if action.target:
                    await self.browser_session.navigate(action.target)
                    print(f"[Agent] ✓ Navigated to {action.target}", flush=True)
                    return True
                    
            elif action.action_type == "go_back":
                try:
                    await self.browser_session.page.go_back()
                    print(f"[Agent] ✓ Went back", flush=True)
                    await asyncio.sleep(0.3)  # Wait for page to load
                    return True
                except Exception as e:
                    print(f"[Agent] ⚠️ Go back failed: {e}", flush=True)
                    return False
                    
            elif action.action_type == "wait":
                await asyncio.sleep(1)
                print(f"[Agent] ✓ Waited", flush=True)
                return True
                
            return False
            
        except Exception as e:
            print(f"[Agent] ❌ Action failed: {e}", flush=True)
            return False
    
    async def _refresh_page_context(self) -> Optional[dict]:
        """Refresh page context after an action and update presenter."""
        if not self.browser_session:
            return None
        
        try:
            # Wait for page to stabilize after navigation/click
            await asyncio.sleep(0.3)  # Give JS time to render
            
            page_context = await self.browser_session.get_page_content()
            self.presenter.update_page_context(page_context)
            
            # Log the new page state for debugging
            new_url = page_context.get("url", "")
            new_title = page_context.get("title", "")
            print(f"[Agent] 🔄 Page context refreshed: {new_title}", flush=True)
            
            return page_context
        except Exception as e:
            print(f"[Agent] ⚠️ Could not refresh page context: {e}", flush=True)
            return None
    
    async def _run_playbook(self) -> None:
        """Run the loaded playbook as a scripted demo."""
        if not self.playbook or not self.browser_session:
            print("[Agent] ⚠️ Cannot run playbook: missing playbook or browser", flush=True)
            return
        
        print(f"[Agent] 🎬 Starting playbook: {self.playbook.name}", flush=True)
        
        # Navigate to home page first (demo should always start from home)
        home_url = getattr(self.presenter.persona, 'home_url', '')
        if home_url:
            print(f"[Agent] 🏠 Navigating to home page before demo: {home_url}", flush=True)
            await self._speak("Sure! Let me give you a quick tour. One moment while I take you to the home page.")
            success = await self.browser_session.navigate(home_url)
            if success:
                await asyncio.sleep(0.3)  # Wait for page to load
                print(f"[Agent] ✓ Now on home page, starting demo", flush=True)
            else:
                print(f"[Agent] ⚠️ Could not navigate to home, starting demo anyway", flush=True)
        
        # Create the demo runner with callbacks and persona for dynamic narration
        # Reset demo interruption flag
        self._demo_interrupted = False
        self.demo_runner = DemoRunner(
            browser_session=self.browser_session,
            speak_callback=self._speak,
            check_interrupted=lambda: self._demo_interrupted or not self.is_running,
            persona=self.presenter.persona
        )
        
        try:
            # Run the playbook
            success = await self.demo_runner.run_playbook(self.playbook)
            
            if success:
                print(f"[Agent] ✓ Playbook completed successfully", flush=True)
            else:
                print(f"[Agent] ⚠️ Playbook ended early (interrupted or failed)", flush=True)
                
        except Exception as e:
            print(f"[Agent] ❌ Playbook error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            self.demo_runner = None
            self.is_speaking = False
    
    async def _browser_scroll(self, direction: str) -> None:
        """Handle scroll action from LLM."""
        if self.browser_session:
            await self.browser_session.scroll(direction)
    
    async def _browser_click(self, element_text: str) -> bool:
        """Handle click action - uses smart DOM-based clicking."""
        if not self.browser_session:
            return False
        
        # Sanitize input: remove newlines, collapse spaces
        element_text = element_text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        element_text = ' '.join(element_text.split()).strip()
        
        # Extract core text without trailing badges/symbols (e.g., "Sister Circle !" -> "Sister Circle")
        core_text = re.sub(r'\s*[!@#$%^&*()0-9]+\s*$', '', element_text).strip()
        
        # === STRATEGY 1: Smart click (DOM-based, most reliable) ===
        # This searches the actual DOM, finds the element, and clicks it or its clickable parent
        texts_to_try = [element_text]
        if core_text and core_text != element_text:
            texts_to_try.insert(0, core_text)
        
        for text in texts_to_try:
            if await self.browser_session.smart_click(text):
                print(f"[Agent] ✓ Smart clicked '{text}'", flush=True)
                return True
        
        # === STRATEGY 2: Playwright selectors as fallback ===
        print(f"[Agent] Smart click failed, trying Playwright selectors...", flush=True)
        for text in texts_to_try:
            selectors = [
                f"text={text}",
                f"button:has-text('{text}')",
                f"a:has-text('{text}')",
                f"[role='button']:has-text('{text}')",
            ]
            for selector in selectors:
                try:
                    if await self.browser_session.click(selector, timeout=1000):
                        print(f"[Agent] ✓ Clicked via selector", flush=True)
                        return True
                except Exception:
                    pass
        
        print(f"[Agent] ❌ FAILED to click: {element_text}", flush=True)
        return False
    
    async def _find_best_element(self, intent: str) -> Optional[str]:
        """Use LLM to find the best matching element for an intent."""
        if not self.browser_session:
            return None
        
        try:
            # Get available elements from the page (no delay - we wait after navigation)
            page_content = await self.browser_session.get_page_content()
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
            
            if answer.upper() == "NONE":
                return None
            
            # Check if answer is in available list (exact or partial)
            if answer in available:
                return answer
            
            # Try partial match
            for el in available:
                if answer.lower() in el.lower() or el.lower() in answer.lower():
                    return el
            
            return None
            
        except Exception as e:
            print(f"[Agent] Error finding element match: {e}", flush=True)
            return None
    
    async def leave_room(self) -> None:
        """Leave the current room and clean up."""
        print("[Agent] Leaving room...")
        self.is_running = False
        
        # Deepgram connection will be closed by context manager
        self._dg_connection = None
        
        # Leave Daily call with proper cleanup
        if self.client:
            try:
                self.client.leave()
                await asyncio.sleep(0.5)  # Let leave complete
                self.client.release()
            except Exception as e:
                print(f"[Agent] Leave error (ignoring): {e}", flush=True)
            self.client = None
        
        # Clean up virtual devices
        self.mic = None
        self.speaker = None
        
        self.llm.reset_conversation()
        print("[Agent] ✓ Left room")


# Singleton agent manager
_active_agents: dict[str, AIAgent] = {}


async def spawn_agent(room_name: str, room_url: str, token: str, company_id: Optional[str] = None) -> AIAgent:
    """Spawn an AI agent for a room with optional company persona."""
    # Clean up any existing agent first
    if room_name in _active_agents:
        print(f"[Agent] Cleaning up existing agent for {room_name}", flush=True)
        try:
            old_agent = _active_agents.pop(room_name)
            await old_agent.leave_room()
            # Wait for Daily SDK to fully release resources
            await asyncio.sleep(2)
            print("[Agent] Cleanup complete, spawning new agent...", flush=True)
        except Exception as e:
            print(f"[Agent] Cleanup error (ignoring): {e}", flush=True)
            await asyncio.sleep(1)
    
    agent = AIAgent(company_id=company_id)
    _active_agents[room_name] = agent
    
    # Run in background task with error handling
    async def run_agent():
        try:
            await agent.join_room(room_name, room_url, token)
        except Exception as e:
            print(f"[Agent] ❌ Agent task failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
    
    asyncio.create_task(run_agent())
    
    return agent


async def remove_agent(room_name: str) -> None:
    """Remove and cleanup an agent for a room."""
    if room_name in _active_agents:
        agent = _active_agents.pop(room_name)
        await agent.leave_room()


def get_agent(room_name: str) -> Optional[AIAgent]:
    """Get the active agent for a room."""
    return _active_agents.get(room_name)
