"""
Speech-to-Text Service using Deepgram.
Handles real-time audio transcription.
"""

from typing import AsyncIterator, Callable
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions

from app.core.config import get_settings


class STTService:
    """Deepgram-based Speech-to-Text service."""
    
    def __init__(self):
        settings = get_settings()
        self.client = DeepgramClient(settings.deepgram_api_key)
        self.connection = None
        self._on_transcript: Callable[[str], None] | None = None
    
    async def start_stream(self, on_transcript: Callable[[str], None]) -> None:
        """
        Start a streaming transcription session.
        
        Args:
            on_transcript: Callback function called with each transcribed text chunk
        """
        self._on_transcript = on_transcript
        
        # Configure live transcription options
        options = LiveOptions(
            model="nova-2",
            language="en",
            smart_format=True,
            interim_results=True,
            utterance_end_ms=1000,
            vad_events=True,
            endpointing=300,
        )
        
        # Create live transcription connection
        self.connection = self.client.listen.live.v("1")
        
        # Set up event handlers
        self.connection.on(LiveTranscriptionEvents.Transcript, self._handle_transcript)
        self.connection.on(LiveTranscriptionEvents.Error, self._handle_error)
        
        # Start the connection
        await self.connection.start(options)
    
    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio data to Deepgram for transcription."""
        if self.connection:
            await self.connection.send(audio_data)
    
    async def stop_stream(self) -> None:
        """Stop the transcription stream."""
        if self.connection:
            await self.connection.finish()
            self.connection = None
    
    def _handle_transcript(self, *args, **kwargs) -> None:
        """Handle incoming transcription results."""
        result = kwargs.get("result")
        if result and self._on_transcript:
            transcript = result.channel.alternatives[0].transcript
            if transcript and result.is_final:
                self._on_transcript(transcript)
    
    def _handle_error(self, *args, **kwargs) -> None:
        """Handle transcription errors."""
        error = kwargs.get("error")
        print(f"[STT] Error: {error}")

