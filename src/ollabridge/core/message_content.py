"""What a chat message carries: text, and the images that ride with it.

OpenAI-style clients send an image as a content part::

    {"role": "user", "content": [
        {"type": "text", "text": "What is on this slide?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR..."}},
    ]}

The gateway used to flatten every message to its text before routing it, so the image was
dropped on the floor and a vision model answered as if it had been sent text alone — asked
for the colour of a red square, ``internal-gemma4-31b`` replied "NO IMAGE". These helpers let
each route keep what it can carry: the OpenAI shape for OpenAI-compatible upstreams, Ollama's
``images`` field for Ollama, Gemini's ``inline_data`` for Gemini.

A message without images is reduced to exactly the plain string it always was, so every
existing payload is byte-for-byte unchanged.
"""

from __future__ import annotations

import re
from typing import Any

_DATA_URI = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)?(?P<params>(;[\w-]+=[^;,]*)*)(?P<b64>;base64)?,(?P<data>.*)$", re.S)


def text_of(content: Any) -> str:
    """The text of any accepted content shape (string, list of parts, or None)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


def image_urls(content: Any) -> list[str]:
    """The ``image_url`` parts of a content list, as URLs (``data:`` or ``http(s):``)."""
    if not isinstance(content, list):
        return []
    urls: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") not in ("image_url", "input_image"):
            continue
        ref = block.get("image_url")
        url = ref.get("url") if isinstance(ref, dict) else ref
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


def has_images(content: Any) -> bool:
    return bool(image_urls(content))


def split_data_uri(url: str) -> tuple[str, str] | None:
    """``(mime, base64)`` for a base64 ``data:`` URI, else ``None``."""
    match = _DATA_URI.match(url or "")
    if not match or not match.group("b64"):
        return None
    return (match.group("mime") or "image/png"), match.group("data").strip()


def ollama_images(content: Any) -> list[str]:
    """Base64 images for Ollama's ``images`` field. Ollama takes no URLs, so only ``data:``
    images can be carried; remote URLs are left to the caller to fetch or refuse."""
    out: list[str] = []
    for url in image_urls(content):
        split = split_data_uri(url)
        if split:
            out.append(split[1])
    return out


def openai_content(content: Any) -> Any:
    """Content for an OpenAI-compatible upstream: the list kept when it carries images,
    otherwise the same plain string the gateway always sent."""
    if has_images(content):
        return [b for b in content if isinstance(b, dict)]
    return text_of(content)


def _guess_mime(b64: str) -> str:
    """An image type from the first base64 characters (Ollama's ``images`` carry no type)."""
    head = (b64 or "")[:12]
    if head.startswith("/9j/"):
        return "image/jpeg"
    if head.startswith("iVBOR"):
        return "image/png"
    if head.startswith("R0lG"):
        return "image/gif"
    if head.startswith("UklG"):
        return "image/webp"
    return "image/png"


def with_images(content: Any, images: Any) -> Any:
    """Content with Ollama-style ``images`` (bare base64) folded in as OpenAI image parts.

    OllaBridge Cloud relays a request to this gateway in Ollama's shape — the text in
    ``content`` and the pictures beside it in ``images`` — and so do Ollama-native clients.
    The gateway's own model has no ``images`` field, so they were dropped on arrival, and a
    vision request routed through the Cloud reached the model without its picture. Folding
    them into content parts here gives every route one shape to read them from.
    """
    pictures = [i for i in (images or []) if isinstance(i, str) and i.strip()]
    if not pictures:
        return content
    parts: list[Any] = []
    if isinstance(content, list):
        parts.extend(content)
    elif content:
        parts.append({"type": "text", "text": str(content)})
    for b64 in pictures:
        b64 = b64.strip()
        url = b64 if b64.startswith("data:") else f"data:{_guess_mime(b64)};base64,{b64}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


def gemini_parts(content: Any) -> list[dict[str, Any]]:
    """Gemini ``parts`` for one message: its text, then each ``data:`` image as inline data."""
    parts: list[dict[str, Any]] = []
    text = text_of(content)
    if text or not has_images(content):
        parts.append({"text": text})
    for url in image_urls(content):
        split = split_data_uri(url)
        if split:
            parts.append({"inline_data": {"mime_type": split[0], "data": split[1]}})
    return parts
