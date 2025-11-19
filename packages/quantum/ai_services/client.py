# ai_services/client.py
from google import genai
from functools import lru_cache
import os

@lru_cache()
def get_gemini_client():
    """Singleton Gemini client with automatic retry handling"""
    return genai.Client(
        api_key=os.getenv("GEMINI_API_KEY")
    )
