"""
AI Agent Service.
Orchestrates the voice AI pipeline: joins Daily calls, listens, thinks, speaks.

Pipeline: Daily Audio → Flux STT → Custom LLM → TTS → Daily Audio
"""

import asyncio
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
from app.core.config import get_settings


class DailyEventHandler(EventHandler):
    """Event handler to monitor Daily call events."""
    
    def __init__(self, agent: 'AIAgent'):
        self.agent = agent
    
    def on_participant_joined(self, participant):
        print(f"[Daily Event] Participant joined: {participant.get('id', 'unknown')}", flush=True)
    
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
    
    def __init__(self):
        settings = get_settings()
        
        # Services
        self.llm = LLMService()
        self.tts = TTSService()
        self.deepgram = AsyncDeepgramClient(api_key=settings.deepgram_api_key)
        
        # Daily client
        self.client: Optional[CallClient] = None
        self.speaker: Optional[VirtualSpeakerDevice] = None
        self.mic: Optional[VirtualMicrophoneDevice] = None
        
        # State
        self.is_running = False
        self.is_speaking = False
        self.room_url: str = ""
        self.token: str = ""
        
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
        
        # Initialize conversation memory
        await self.llm.set_room(room_name)
        
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
            
            # Wait for WebRTC to stabilize
            await asyncio.sleep(1)
            
            # Subscribe to all participants' audio
            self.client.update_subscription_profiles({
                "base": {
                    "camera": "unsubscribed",
                    "microphone": "subscribed",
                }
            })
            
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
                                
                                # Barge-in: stop AI if it's speaking
                                if self.is_speaking:
                                    print("[Agent] 🛑 User interrupted - stopping speech", flush=True)
                                    self.is_speaking = False
                                
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
        """Generate and speak a response."""
        self.is_speaking = True
        
        try:
            print(f"[Agent] 💬 Responding to: '{user_message}'")
            
            # Get LLM response
            response_text = await self.llm.get_response(user_message)
            print(f"[Agent] 🤖 Response: '{response_text}'")
            
            # Convert to speech
            audio_data = await self.tts.synthesize(response_text)
            print(f"[Agent] 🔊 Generated {len(audio_data)} bytes of audio", flush=True)
            
            # Send audio via VirtualMicrophoneDevice (publishes as regular mic track)
            if self.mic and audio_data:
                print(f"[Agent] 📤 Streaming {len(audio_data)} bytes...", flush=True)
                
                def write_audio_sync():
                    """Write audio - blocking mic handles pacing internally."""
                    # Use larger chunks (100ms) for smoother playback
                    # 100ms = 1600 samples = 3200 bytes at 16kHz 16-bit
                    chunk_ms = 100
                    samples_per_chunk = int(self.SAMPLE_RATE * (chunk_ms / 1000.0))  # 1600
                    chunk_bytes = samples_per_chunk * 2  # 3200 bytes
                    
                    chunks_sent = 0
                    interrupted = False
                    for i in range(0, len(audio_data), chunk_bytes):
                        # Stop if user interrupted (barge-in) or agent is shutting down
                        if not self.is_speaking or not self.is_running:
                            interrupted = True
                            break
                        chunk = audio_data[i:i + chunk_bytes]
                        try:
                            # Blocking mic handles real-time pacing internally
                            self.mic.write_frames(chunk)
                            chunks_sent += 1
                        except Exception as e:
                            print(f"[Agent] ❌ Audio write error: {e}", flush=True)
                            break
                    return (chunks_sent, interrupted)
                
                chunks_sent, interrupted = await asyncio.to_thread(write_audio_sync)
                if interrupted:
                    print(f"[Agent] ⏹️ Speech interrupted after {chunks_sent} chunks", flush=True)
                else:
                    print(f"[Agent] ✓ Finished speaking ({chunks_sent} chunks)", flush=True)
            else:
                print(f"[Agent] ⚠️ Cannot send audio: mic={self.mic is not None}", flush=True)
                
        except Exception as e:
            print(f"[Agent] Error generating response: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.is_speaking = False
    
    async def leave_room(self) -> None:
        """Leave the current room and clean up."""
        print("[Agent] Leaving room...")
        self.is_running = False
        
        # Deepgram connection will be closed by context manager
        self._dg_connection = None
        
        # Leave Daily call
        if self.client:
            self.client.leave()
            self.client.release()
            self.client = None
        
        self.llm.reset_conversation()
        print("[Agent] ✓ Left room")


# Singleton agent manager
_active_agents: dict[str, AIAgent] = {}


async def spawn_agent(room_name: str, room_url: str, token: str) -> AIAgent:
    """Spawn an AI agent for a room."""
    # Clean up any existing agent first
    if room_name in _active_agents:
        print(f"[Agent] Cleaning up existing agent for {room_name}", flush=True)
        try:
            old_agent = _active_agents.pop(room_name)
            await old_agent.leave_room()
        except Exception as e:
            print(f"[Agent] Cleanup error (ignoring): {e}", flush=True)
    
    agent = AIAgent()
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
