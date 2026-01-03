"""
Text-to-Speech Service using ElevenLabs.
Handles converting text responses to audio.
"""

from elevenlabs.client import AsyncElevenLabs

from app.core.config import get_settings


class TTSService:
    """ElevenLabs-based Text-to-Speech service."""
    
    def __init__(self):
        settings = get_settings()
        self.client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
        # "Aria" - expressive, natural female voice from ElevenLabs
        self.voice_id = "UgBBYS2sOqTuMpoF3BR0"  # From ElevenLabs voice library
        self.model_id = "eleven_multilingual_v2"  # Best quality, most natural
    
    async def synthesize(self, text: str) -> bytes:
        """
        Convert text to speech audio at 16kHz for Daily.
        
        Args:
            text: The text to convert to speech
            
        Returns:
            Audio data as bytes (16kHz, 16-bit PCM)
        """
        # Generate audio with ElevenLabs at native 16kHz - no resampling needed
        audio_chunks = []
        
        async for chunk in self.client.text_to_speech.convert(
            voice_id=self.voice_id,
            text=text,
            model_id=self.model_id,
            output_format="pcm_16000",  # Native 16kHz 16-bit PCM - matches Daily exactly
        ):
            audio_chunks.append(chunk)
        
        # Combine all chunks - no resampling needed!
        audio_data = b"".join(audio_chunks)
        
        return audio_data
