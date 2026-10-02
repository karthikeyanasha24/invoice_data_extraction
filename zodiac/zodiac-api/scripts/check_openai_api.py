"""Check whether an OpenAI API key can authenticate, without making a model call.

The key is read from OPENAI_API_KEY or entered with a hidden prompt. It is never
printed or saved. The script uses the GET /v1/models endpoint, which does not
consume model tokens.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        api_key = getpass.getpass("OpenAI API key (input hidden): ").strip()
    if not api_key:
        print("No API key provided.")
        return 2

    request = Request(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
            model_count = len(payload.get("data", []))
            print(f"Authentication succeeded (HTTP {response.status}); {model_count} models visible to this key.")
            return 0
    except HTTPError as exc:
        # Do not print the response body; API error payloads may echo key fragments.
        if exc.code == 401:
            print("Authentication failed (HTTP 401). Check that the key is valid and active.")
        elif exc.code == 403:
            print("The key was recognized but this account/project is not authorized (HTTP 403).")
        else:
            print(f"OpenAI returned HTTP {exc.code}.")
        return 1
    except (URLError, TimeoutError) as exc:
        print(f"Could not reach OpenAI: {exc.reason if isinstance(exc, URLError) else 'request timed out'}")
        return 1
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Could not read the API response: {type(exc).__name__}.")
        return 1
    finally:
        # Best-effort cleanup of our local reference; Python strings cannot be zeroed reliably.
        api_key = ""


if __name__ == "__main__":
    sys.exit(main())
