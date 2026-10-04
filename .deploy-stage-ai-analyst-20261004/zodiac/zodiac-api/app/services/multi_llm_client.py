"""
Multi-LLM client supporting OpenAI, Anthropic, Google, and OpenRouter.
Provides unified interface for different AI providers.
"""
import logging
from typing import Any, Dict, List, Optional
import os

logger = logging.getLogger(__name__)


class MultiLLMClient:
    """Unified client for multiple LLM providers."""
    
    def __init__(
        self,
        openai_key: Optional[str] = None,
        anthropic_key: Optional[str] = None,
        google_key: Optional[str] = None,
        openrouter_key: Optional[str] = None,
    ):
        self.openai_key = openai_key
        self.anthropic_key = anthropic_key
        self.google_key = google_key
        self.openrouter_key = openrouter_key
        
        self._openai_client = None
        self._anthropic_client = None
        self._google_client = None
    
    def _get_openai_client(self):
        """Lazy load OpenAI client."""
        if not self._openai_client and self.openai_key:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self.openai_key)
        return self._openai_client
    
    def _get_anthropic_client(self):
        """Lazy load Anthropic client."""
        if not self._anthropic_client and self.anthropic_key:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=self.anthropic_key)
            except ImportError:
                logger.warning("anthropic package not installed. Install with: pip install anthropic")
        return self._anthropic_client
    
    def _get_google_client(self):
        """Lazy load Google Gemini client."""
        if not self._google_client and self.google_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.google_key)
                self._google_client = genai
            except ImportError:
                logger.warning("google-generativeai package not installed. Install with: pip install google-generativeai")
        return self._google_client
    
    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.4,
        max_tokens: int = 800,
    ) -> str:
        """
        Unified chat completion across providers.
        
        Args:
            model: Model identifier (e.g., "gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro")
            messages: List of message dicts with "role" and "content"
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
        
        Returns:
            Generated text response
        """
        model_lower = model.lower()
        
        # OpenAI models
        if model_lower.startswith("gpt") or model_lower.startswith("o1"):
            return self._openai_completion(model, messages, temperature, max_tokens)
        
        # Anthropic Claude models
        elif "claude" in model_lower:
            return self._anthropic_completion(model, messages, temperature, max_tokens)
        
        # Google Gemini models
        elif "gemini" in model_lower:
            return self._google_completion(model, messages, temperature, max_tokens)
        
        # OpenRouter (prefix with openrouter/)
        elif model_lower.startswith("openrouter/"):
            return self._openrouter_completion(model, messages, temperature, max_tokens)
        
        else:
            # Fallback to OpenAI
            logger.warning(f"Unknown model '{model}', falling back to OpenAI")
            return self._openai_completion(model, messages, temperature, max_tokens)
    
    def _openai_completion(self, model: str, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> str:
        """OpenAI chat completion."""
        client = self._get_openai_client()
        if not client:
            raise ValueError("OpenAI API key not configured")
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
    
    def _anthropic_completion(self, model: str, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> str:
        """Anthropic Claude chat completion."""
        client = self._get_anthropic_client()
        if not client:
            raise ValueError("Anthropic API key not configured or package not installed")
        
        try:
            # Convert messages format
            system_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
            user_messages = [{"role": m["role"], "content": m["content"]} 
                           for m in messages if m["role"] != "system"]
            
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_msg if system_msg else "",
                messages=user_messages or [{"role": "user", "content": messages[0]["content"]}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            raise
    
    def _google_completion(self, model: str, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> str:
        """Google Gemini chat completion."""
        genai = self._get_google_client()
        if not genai:
            raise ValueError("Google API key not configured or package not installed")
        
        try:
            # Convert to Gemini format (just concatenate for now)
            prompt = "\n\n".join([f"{m['role'].upper()}: {m['content']}" for m in messages])
            
            model_instance = genai.GenerativeModel(model)
            response = model_instance.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                )
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Google Gemini API error: {e}")
            raise
    
    def _openrouter_completion(self, model: str, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> str:
        """OpenRouter completion (supports many models)."""
        if not self.openrouter_key:
            raise ValueError("OpenRouter API key not configured")
        
        try:
            from openai import OpenAI
            # OpenRouter uses OpenAI-compatible API
            client = OpenAI(
                api_key=self.openrouter_key,
                base_url="https://openrouter.ai/api/v1"
            )
            
            # Remove "openrouter/" prefix for API call
            actual_model = model.replace("openrouter/", "")
            
            response = client.chat.completions.create(
                model=actual_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            raise


def get_multi_llm_client() -> MultiLLMClient:
    """Get configured multi-LLM client."""
    from ..config.config import OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, OPENROUTER_API_KEY
    
    return MultiLLMClient(
        openai_key=OPENAI_API_KEY,
        anthropic_key=ANTHROPIC_API_KEY,
        google_key=GOOGLE_API_KEY,
        openrouter_key=OPENROUTER_API_KEY,
    )


def get_best_available_model() -> str:
    """
    Automatically select the best available model for deep insights.
    
    Priority order (most reliable and capable first):
    1. GPT-4o - OpenAI's most reliable, best reasoning, most trusted
    2. Claude 3.5 Sonnet - Anthropic's best, excellent business analysis
    3. Gemini 1.5 Pro - Google's strong model, great insights
    4. GPT-4o-mini - Fast fallback
    
    Returns:
        Model identifier string
    """
    from ..config.config import OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY
    
    # Priority 1: GPT-4o (most reliable, best reasoning)
    if OPENAI_API_KEY:
        logger.info("🏆 Auto-selected GPT-4o for insights (highest reliability & depth)")
        return "gpt-4o"
    
    # Priority 2: Claude 3.5 Sonnet (excellent analysis)
    if ANTHROPIC_API_KEY:
        try:
            import anthropic
            logger.info("🏆 Auto-selected Claude 3.5 Sonnet for insights (excellent business analysis)")
            return "claude-3-5-sonnet-20241022"
        except ImportError:
            logger.warning("Anthropic key found but package not installed")
    
    # Priority 3: Gemini 1.5 Pro (great quality)
    if GOOGLE_API_KEY:
        try:
            import google.generativeai
            logger.info("🏆 Auto-selected Gemini 1.5 Pro for insights (strong analysis)")
            return "gemini-1.5-pro"
        except ImportError:
            logger.warning("Google key found but package not installed")
    
    # Fallback: GPT-4o-mini
    logger.warning("⚠️ No premium model keys configured, using GPT-4o-mini fallback")
    return "gpt-4o-mini"


def smart_chat_completion(
    messages: List[Dict[str, str]],
    temperature: float = 0.4,
    max_tokens: int = 1500,
    require_premium: bool = True,
) -> tuple[str, str]:
    """
    Intelligent chat completion with automatic model selection and fallback.
    
    Tries models in priority order:
    1. GPT-4o (most reliable)
    2. Claude 3.5 Sonnet (excellent analysis)
    3. Gemini 1.5 Pro (strong quality)
    4. GPT-4o-mini (fast fallback)
    
    Args:
        messages: Chat messages
        temperature: Sampling temperature
        max_tokens: Max tokens to generate
        require_premium: If True, tries premium models first
    
    Returns:
        Tuple of (generated_text, model_used)
    """
    client = get_multi_llm_client()
    
    # Define model priority list
    if require_premium:
        model_priority = [
            ("gpt-4o", "OpenAI GPT-4o"),
            ("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet"),
            ("gemini-1.5-pro", "Gemini 1.5 Pro"),
            ("gpt-4o-mini", "GPT-4o-mini (fallback)"),
        ]
    else:
        model_priority = [
            ("gpt-4o-mini", "GPT-4o-mini"),
        ]
    
    # Try each model in priority order
    last_error = None
    for model, model_name in model_priority:
        try:
            logger.info(f"🔄 Trying {model_name}...")
            response = client.chat_completion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            logger.info(f"✅ Success with {model_name}")
            return response, model
        except Exception as e:
            logger.warning(f"❌ {model_name} failed: {str(e)[:100]}")
            last_error = e
            continue
    
    # All models failed
    raise Exception(f"All models failed. Last error: {last_error}")
