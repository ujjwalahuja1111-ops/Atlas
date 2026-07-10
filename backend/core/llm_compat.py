"""LLM chat compatibility shim (Sprint DX-2 — Remove Emergent Runtime Dependency).

Atlas's Intelligence Engine (Sprint 2/3) talks to GPT-4o for multi-modal
(text + image) chat completions via `emergentintegrations.llm.chat` — a
package only installable inside Emergent's hosted environment (it is not
published to public PyPI), which broke `python -m pip install -r
requirements.txt` on any standard Windows/macOS/Linux machine.

`EMERGENT_BASE_URL` (see core/settings.py) is, and always was, a plain
OpenAI-API-compatible endpoint — its default value literally ends in
`/llm/openai/v1`, and `intelligence_engine.py` already talks to it
directly via the standard `openai` package for Whisper transcription
(`_openai_client = OpenAI(api_key=EMERGENT_LLM_KEY, base_url=EMERGENT_BASE_URL)`).
So the two call sites that used `emergentintegrations.llm.chat`
(`_structure()` and `summarise_voice_update()`) never actually needed a
proprietary client — they need a standard OpenAI-protocol chat
completions call against that same endpoint.

This module is the adapter, and the ONLY file in Atlas that imports
`emergentintegrations`:
  - When it IS available (Emergent-hosted environments), it is imported
    and re-exported completely unchanged — zero behavioural difference
    on Emergent deployments, byte-for-byte the same code path as before
    this patch.
  - When it is NOT available (any standard local install), the fallback
    below reimplements the exact subset of the LlmChat/UserMessage/
    ImageContent interface `intelligence_engine.py` actually calls, via
    the standard `openai` package hitting the identical
    EMERGENT_BASE_URL/EMERGENT_LLM_KEY. Same endpoint, same protocol,
    same model — only the Python object making the HTTP call differs.

`intelligence_engine.py` imports LlmChat/UserMessage/ImageContent from
HERE, never directly from `emergentintegrations` — this is the isolation
boundary the task asked for.
"""
from __future__ import annotations
import asyncio
from typing import Optional

try:
    # Real thing, when available. Re-exported completely unchanged so any
    # environment that does have Emergent's private package behaves
    # exactly as it did before this patch.
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent  # type: ignore  # noqa: F401

except ImportError:
    from openai import OpenAI
    from core.settings import EMERGENT_BASE_URL

    class ImageContent:
        """Matches emergentintegrations.llm.chat.ImageContent's observed
        interface: an object holding a base64-encoded image."""

        def __init__(self, image_base64: str):
            self.image_base64 = image_base64

    class UserMessage:
        """Matches emergentintegrations.llm.chat.UserMessage's observed
        interface: text plus optional image attachments."""

        def __init__(self, text: str, file_contents: Optional[list] = None):
            self.text = text
            self.file_contents = file_contents or []

    class LlmChat:
        """Local fallback for emergentintegrations.llm.chat.LlmChat,
        matching only the subset of its interface Atlas actually calls:
        construct with (api_key, session_id, system_message), chain
        .with_model(provider, model), then `await send_message(msg)` ->
        str.

        Implemented as a plain OpenAI-protocol chat completion against
        EMERGENT_BASE_URL — which is what the real package talks to as
        well (see module docstring). `session_id` is accepted for
        interface compatibility but unused, matching the real client
        never exposing it back to callers either. The blocking SDK call
        is run in a thread, mirroring the exact pattern this file's
        caller (`_whisper_transcribe`) already uses for the Whisper call.
        """

        def __init__(self, api_key: str, session_id: str, system_message: str):
            self._client = OpenAI(api_key=api_key, base_url=EMERGENT_BASE_URL)
            self._system_message = system_message
            self._model = "gpt-4o"  # overwritten by with_model(); safe default

        def with_model(self, provider: str, model: str) -> "LlmChat":
            self._model = model
            return self

        async def send_message(self, message: "UserMessage") -> str:
            content: list = [{"type": "text", "text": message.text}]
            for f in message.file_contents:
                b64 = getattr(f, "image_base64", None)
                if b64:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    })
            messages = [
                {"role": "system", "content": self._system_message},
                {"role": "user", "content": content},
            ]

            def _run() -> str:
                resp = self._client.chat.completions.create(model=self._model, messages=messages)
                return resp.choices[0].message.content or ""

            return await asyncio.to_thread(_run)
