"""Shared live-acceptance HTTP helpers. Token is never printed."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Dict


def _login_token() -> str:
    email = (os.environ.get("LIVE_API_EMAIL") or "").strip()
    password = os.environ.get("LIVE_API_PASSWORD") or ""
    if not email or not password:
        return ""
    base = (os.environ.get("LIVE_API_BASE") or "https://zodiac-back.vercel.app").rstrip("/")
    url = f"{base}/api/v1/user/auth/login"
    body = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    return (payload.get("access_token") or payload.get("token") or "").strip()


def adaptive_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = (os.environ.get("LIVE_API_TOKEN") or os.environ.get("ZODIAC_LIVE_TOKEN") or "").strip()
    if not token:
        token = _login_token()
        if token:
            os.environ["LIVE_API_TOKEN"] = token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
