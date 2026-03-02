"""
Vercel entry point for Zodiac API
This file exposes the FastAPI app for Vercel's serverless Python runtime
"""
from app.server import app

# Vercel expects the ASGI application to be named 'app' or exposed as a handler
handler = app
