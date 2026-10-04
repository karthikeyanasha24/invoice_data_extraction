"""
Vercel entry point for Zodiac API
This file exposes the FastAPI app for Vercel's serverless Python runtime
"""
import sys
import os

# Ensure the app directory is in the Python path
sys.path.insert(0, os.path.dirname(__file__))

from app.server import app

# Simply export the app - Vercel will auto-detect it as an ASGI application
# The variable name must be 'app' for Vercel's Python runtime to find it
