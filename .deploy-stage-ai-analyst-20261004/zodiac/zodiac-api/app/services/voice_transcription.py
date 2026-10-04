"""
Voice transcription service using OpenAI Whisper API.

Provides high-accuracy audio transcription as a fallback/alternative
to browser Web Speech API.
"""
import logging
import tempfile
from typing import Dict, Optional

from openai import OpenAI

from ..config.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)


def transcribe_audio(
    audio_file_content: bytes,
    file_format: str = "webm",
    language: Optional[str] = None,
) -> Dict[str, str]:
    """
    Transcribe audio using OpenAI Whisper API.
    
    Args:
        audio_file_content: Binary audio file content
        file_format: Audio format (webm, mp3, wav, etc.)
        language: Optional language code (e.g., 'en', 'es')
    
    Returns:
        Dictionary with transcription result:
        {
            "text": "transcribed text",
            "language": "detected language",
            "success": True/False,
            "error": "error message if failed"
        }
    """
    try:
        if not OPENAI_API_KEY:
            return {
                "text": "",
                "language": "",
                "success": False,
                "error": "OpenAI API key not configured",
            }
        
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Write audio to temporary file
        with tempfile.NamedTemporaryFile(suffix=f".{file_format}", delete=False) as temp_file:
            temp_file.write(audio_file_content)
            temp_file_path = temp_file.name
        
        try:
            # Call Whisper API
            with open(temp_file_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                    response_format="json",
                )
            
            result_text = transcription.text if hasattr(transcription, 'text') else ""
            detected_language = language or "en"  # Whisper doesn't return detected language in transcriptions
            
            logger.info(f"Whisper transcription successful: {len(result_text)} characters")
            
            return {
                "text": result_text,
                "language": detected_language,
                "success": True,
                "error": None,
            }
        
        finally:
            # Cleanup temp file
            import os
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass
    
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return {
            "text": "",
            "language": "",
            "success": False,
            "error": str(e),
        }
