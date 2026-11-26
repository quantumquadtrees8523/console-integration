"""One chat-completion call to the model provider, with tools. The only place Console talks to it.

The key is the household's own, minted by the relay with this month's remaining allowance as its limit
and a few hours to live. What goes to the provider: the conversation, the tool list and tool results.

With `on_delta` the answer is streamed: the model's thinking and its words are handed over as they
arrive, so the chat card can show what is happening while it happens.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import Any

import aiohttp

from .const import MODEL_TIMEOUT_S

STREAM_TIMEOUT_S = 90


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
    thinking: str = ""


Delta = Callable[[str, str], None]  # ("thinking" | "text", the new piece)


def _refuse(status: int, error: Any) -> None:
    """Raise for a refusal the provider gave before answering."""
    if status in (402, 403):
        # OpenRouter's pages disagree on which of the two a spent key gets; both mean the same here.
        raise LimitReached(str(status))
    if status == 401:
        raise KeyRejected(str(status))
    if status >= 400 or error:
        code = error.get("code") if isinstance(error, dict) else None
        raise ModelError(f"http {status}" + (f" code {code}" if code else ""))


async def complete(
    session: aiohttp.ClientSession,
    inference: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    effort: str,
    timeout_s: float = MODEL_TIMEOUT_S,
    on_delta: Delta | None = None,
) -> Completion:
    body: dict[str, Any] = {"model": model, "messages": messages, "reasoning": {"effort": effort}}
    if tools:
        body["tools"] = tools
    headers = {"Authorization": f"Bearer {inference['key']}", "X-Title": "Console"}
    url = inference["base_url"].rstrip("/") + "/chat/completions"
    if on_delta is not None:
        return await _stream(session, url, headers, body | {"stream": True}, model, on_delta)
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

    _refuse(status, data.get("error") if isinstance(data, dict) else None)
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as error_:
        raise ModelError("no choices") from error_
    if choice.get("finish_reason") == "error":
        raise ModelError("finish_reason error")
    cost = float((data.get("usage") or {}).get("cost") or 0.0)
    return Completion(
        message=message,
        cost_usd=cost,
        model=str(data.get("model") or model),
        thinking=str(message.get("reasoning") or ""),
    )


async def _stream(
    session: aiohttp.ClientSession, url: str, headers: dict[str, str], body: dict[str, Any], model: str, on_delta: Delta
) -> Completion:
    """The same call, read as it is written: server-sent events, one JSON chunk per `data:` line."""
    text, thinking, cost, used = "", "", 0.0, model
    calls: dict[int, dict[str, Any]] = {}
    try:
        async with asyncio.timeout(STREAM_TIMEOUT_S):
            async with session.post(url, json=body, headers=headers) as answer:
                if answer.status >= 400:
                    try:
                        refused = await answer.json(content_type=None)
                    except ValueError:
                        refused = {}
                    _refuse(answer.status, refused.get("error") if isinstance(refused, dict) else None)
                async for raw in answer.content:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue  # blank lines and ": OPENROUTER PROCESSING" comments
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        raise ModelError("error in the stream")
                    if chunk.get("model"):
                        used = str(chunk["model"])
                    if (chunk.get("usage") or {}).get("cost") is not None:
                        cost = float(chunk["usage"]["cost"] or 0.0)
                    for choice in chunk.get("choices") or []:
                        if choice.get("finish_reason") == "error":
                            raise ModelError("finish_reason error")
                        delta = choice.get("delta") or {}
                        if piece := delta.get("reasoning"):
                            thinking += piece
                            on_delta("thinking", piece)
                        if piece := delta.get("content"):
                            text += piece
                            on_delta("text", piece)
                        for part in delta.get("tool_calls") or []:
                            call = calls.setdefault(int(part.get("index") or 0), {"id": "", "name": "", "arguments": ""})
                            call["id"] = part.get("id") or call["id"]
                            function = part.get("function") or {}
                            call["name"] += function.get("name") or ""
                            call["arguments"] += function.get("arguments") or ""
    except (aiohttp.ClientError, TimeoutError) as error:
        raise ModelError(type(error).__name__) from error

    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
            for _, c in sorted(calls.items())
        ]
    return Completion(message=message, cost_usd=cost, model=used, thinking=thinking)
