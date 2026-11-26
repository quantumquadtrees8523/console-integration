"""One chat-completion call to the model provider, with tools. The only place Console talks to it.

The key is the household's own, minted by the relay with this month's remaining allowance as its limit
and a few hours to live. What goes to the provider: the conversation, the tool list and tool results.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import MODEL_TIMEOUT_S


class ModelError(Exception):
    """The model call failed in a way another model might not: an error, a timeout, an empty answer."""


class KeyRejected(Exception):
    """The provider didn't accept the key (expired, disabled or unknown)."""


class LimitReached(Exception):
    """The key's spending limit is used up."""


@dataclass
class Completion:
    message: dict[str, Any]
    cost_usd: float
    model: str


async def complete(
    session: aiohttp.ClientSession,
    inference: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    effort: str,
    timeout_s: float = MODEL_TIMEOUT_S,
) -> Completion:
    body: dict[str, Any] = {"model": model, "messages": messages, "reasoning": {"effort": effort}}
    if tools:
        body["tools"] = tools
    headers = {"Authorization": f"Bearer {inference['key']}", "X-Title": "Console"}
    url = inference["base_url"].rstrip("/") + "/chat/completions"
    try:
        async with asyncio.timeout(timeout_s):
            async with session.post(url, json=body, headers=headers) as answer:
                status = answer.status
                try:
                    data = await answer.json(content_type=None)
                except ValueError:
                    data = {}
    except (aiohttp.ClientError, TimeoutError) as error:
        raise ModelError(type(error).__name__) from error

    error = data.get("error") if isinstance(data, dict) else None
    if status in (402, 403):
        # OpenRouter's pages disagree on which of the two a spent key gets; both mean the same here.
        raise LimitReached(str(status))
    if status == 401:
        raise KeyRejected(str(status))
    if status >= 400 or error:
        code = (error or {}).get("code") if isinstance(error, dict) else None
        raise ModelError(f"http {status}" + (f" code {code}" if code else ""))
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as error_:
        raise ModelError("no choices") from error_
    if choice.get("finish_reason") == "error":
        raise ModelError("finish_reason error")
    cost = float((data.get("usage") or {}).get("cost") or 0.0)
    return Completion(message=message, cost_usd=cost, model=str(data.get("model") or model))
