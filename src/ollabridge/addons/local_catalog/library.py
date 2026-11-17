"""
Model discovery: find models that are not installed yet.

The catalog (``sync_service``) only knows what the runtime already has. This
module answers "what could I download?" from two places:

- :class:`OllamaLibrary`: the public Ollama library. Ollama has no search
  API, so the search page is fetched server-side and parsed. That is a
  scrape: when the page changes, search returns nothing and pulling by exact
  name still works. Download sizes come from the Ollama registry, the
  protocol ``ollama pull`` itself speaks.
- :class:`HuggingFaceLibrary`: GGUF repositories on the Hugging Face Hub,
  through its public API. Ollama installs them directly as
  ``hf.co/<owner>/<repo>:<quantization>``.

Nothing here downloads a model: that stays with ``pulls.LocalPullManager``.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://ollama.com/search"
REGISTRY_URL = "https://registry.ollama.ai"
USER_AGENT = "ollabridge-model-library"

SEARCH_TTL_S = 10 * 60
MAX_RESULTS = 30
MAX_TAGS = 16

# A model name as the library spells it: ``qwen2.5`` or ``namespace/model``.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)?$", re.I)
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$", re.I)
# A parameter-size chip on a result card: 0.5b, 7b, 235b, 335m, e2b.
_SIZE_RE = re.compile(r"^(e?\d+(\.\d+)?[bmk]|\d+x\d+(\.\d+)?b)$", re.I)

_RESULT_RE = re.compile(
    r'<li[^>]*>\s*<a href="/([^"]+)"[^>]*>(.*?)</a>\s*</li>', re.S
)
# The small rounded labels on a card: parameter sizes and capabilities.
_CHIP_RE = re.compile(r'<span\b[^>]*\bclass="[^"]*\brounded-md\b[^"]*"[^>]*>(.*?)</span>', re.S)
_DESCRIPTION_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_DOWNLOADS_RE = re.compile(r'title="([\d,]+) downloads"')
_TAG_COUNT_RE = re.compile(r">\s*([\d,]+) tags?\s*<")
_UPDATED_RE = re.compile(r'title="Updated ([^"]+)"')
_MARKUP_RE = re.compile(r"<[^>]+>")


HF_API_URL = "https://huggingface.co/api/models"
# A Hub repository id: ``owner/repo``.
_HF_REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")
# The quantization a GGUF file name ends with: ...-Q4_K_M.gguf, ...-F16.gguf.
_QUANT_RE = re.compile(r"[-._]((?:I?Q\d[A-Z0-9_]*|BF16|F16|F32))\.gguf$", re.I)
# One model split over several files; Ollama cannot install those from the Hub.
_SPLIT_RE = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)
# The builds people actually run, best default first. Others follow by size.
_QUANT_ORDER = ("Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "Q4_K_S", "Q3_K_M", "Q4_0", "IQ4_XS", "Q2_K")
MAX_QUANTS = 12


def valid_hf_repo(repo: str) -> bool:
    return bool(_HF_REPO_RE.match(repo or ""))


def gguf_quantizations(siblings: list[dict[str, Any]], repo: str) -> list[dict[str, Any]]:
    """The installable builds in a Hub repository's file list, as pull choices."""
    builds: dict[str, dict[str, Any]] = {}
    for entry in siblings:
        filename = str(entry.get("rfilename") or "")
        if "mmproj" in filename.lower() or _SPLIT_RE.search(filename):
            continue
        match = _QUANT_RE.search(filename)
        if not match:
            continue
        quant = match.group(1).upper()
        if quant in builds:
            continue  # a second file with the same label: keep the first
        builds[quant] = {
            "tag": quant,
            "ref": f"hf.co/{repo}:{quant}",
            "size_bytes": int(entry.get("size") or 0) or None,
            "available": True,
        }

    def rank(build: dict[str, Any]) -> tuple[int, int]:
        tag = build["tag"]
        return (_QUANT_ORDER.index(tag) if tag in _QUANT_ORDER else len(_QUANT_ORDER), build["size_bytes"] or 0)

    return sorted(builds.values(), key=rank)[:MAX_QUANTS]


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or ""))


def valid_tag(tag: str) -> bool:
    return bool(_TAG_RE.match(tag or ""))


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_MARKUP_RE.sub(" ", fragment)).split())


def _int(match: Optional[re.Match]) -> Optional[int]:
    return int(match.group(1).replace(",", "")) if match else None


def parse_search_html(page: str) -> list[dict[str, Any]]:
    """The result cards of an Ollama library search page.

    Tolerant by design: a card missing a field keeps the others, and a page
    with an unknown layout yields an empty list, never an exception.
    """
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for href, body in _RESULT_RE.findall(page):
        if "<h2" not in body:
            continue  # navigation and footer links
        name = href[len("library/"):] if href.startswith("library/") else href
        if not valid_name(name) or name in seen:
            continue
        seen.add(name)
        chips = [_text(chip) for chip in _CHIP_RE.findall(body)]
        description = _DESCRIPTION_RE.search(body)
        updated = _UPDATED_RE.search(body)
        results.append(
            {
                "name": name,
                "description": _text(description.group(1)) if description else "",
                "sizes": [c for c in chips if _SIZE_RE.match(c)],
                "capabilities": [c for c in chips if c and not _SIZE_RE.match(c)],
                "downloads": _int(_DOWNLOADS_RE.search(body)),
                "tag_count": _int(_TAG_COUNT_RE.search(body)),
                "updated": updated.group(1) if updated else None,
            }
        )
        if len(results) >= MAX_RESULTS:
            break
    return results


def manifest_bytes(manifest: dict[str, Any]) -> int:
    """Download size of a registry manifest: its layers plus the config blob."""
    layers = manifest.get("layers") or []
    total = sum(int(layer.get("size") or 0) for layer in layers if isinstance(layer, dict))
    config = manifest.get("config")
    if isinstance(config, dict):
        total += int(config.get("size") or 0)
    return total


class OllamaLibrary:
    """Search and size lookups against the public Ollama library."""

    def __init__(self, *, timeout: float = 15.0, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._timeout = timeout
        self._transport = transport
        self._search_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._size_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            transport=self._transport,
        )

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Models matching ``query``; an empty query lists the popular ones.

        Raises ``httpx.HTTPError`` when the library cannot be reached.
        """
        key = " ".join(query.lower().split())
        cached = self._search_cache.get(key)
        if cached and time.monotonic() - cached[0] < SEARCH_TTL_S:
            return cached[1]
        async with self._http() as client:
            response = await client.get(SEARCH_URL, params={"q": key} if key else None)
            response.raise_for_status()
        results = parse_search_html(response.text)
        if not results:
            logger.warning("ollama library search returned no parseable results for %r", key)
        self._search_cache[key] = (time.monotonic(), results)
        return results

    async def tag_sizes(self, name: str, tags: list[str]) -> list[dict[str, Any]]:
        """Download size per tag, in the order given.

        Only the registry saying "no such tag" makes a tag unavailable. A
        lookup that fails for any other reason (a timeout, a rate limit)
        keeps the tag with an unknown size: hiding a real model because one
        request was slow would be worse than not showing its size.
        """
        repository = name if "/" in name else f"library/{name}"
        wanted = list(dict.fromkeys(tags))[:MAX_TAGS]

        async def one(client: httpx.AsyncClient, tag: str) -> dict[str, Any]:
            ref = f"{name}:{tag}"
            known = self._size_cache.get(ref)
            if known and time.monotonic() - known[0] < SEARCH_TTL_S:
                return dict(known[1])
            row: dict[str, Any] = {"tag": tag, "ref": ref, "size_bytes": None, "available": True}
            try:
                response = await client.get(
                    f"{REGISTRY_URL}/v2/{repository}/manifests/{tag}",
                    headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
                )
                if response.status_code == 200:
                    row["size_bytes"] = manifest_bytes(response.json()) or None
                    self._size_cache[ref] = (time.monotonic(), dict(row))
                elif response.status_code == 404:
                    row["available"] = False
                    self._size_cache[ref] = (time.monotonic(), dict(row))
            except (httpx.HTTPError, ValueError) as exc:
                logger.debug("registry manifest %s failed: %s", ref, exc)
            return row

        async with self._http() as client:
            return list(await asyncio.gather(*(one(client, tag) for tag in wanted)))


class HuggingFaceLibrary:
    """GGUF repositories on the Hugging Face Hub that Ollama can install."""

    def __init__(self, *, timeout: float = 15.0, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._timeout = timeout
        self._transport = transport
        self._search_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            transport=self._transport,
        )

    async def search(self, query: str) -> list[dict[str, Any]]:
        """GGUF repositories matching ``query``, most downloaded first.

        Raises ``httpx.HTTPError`` when the Hub cannot be reached.
        """
        key = " ".join(query.split())
        cached = self._search_cache.get(key.lower())
        if cached and time.monotonic() - cached[0] < SEARCH_TTL_S:
            return cached[1]
        params = {"filter": "gguf", "sort": "downloads", "direction": "-1", "limit": str(MAX_RESULTS)}
        if key:
            params["search"] = key
        async with self._http() as client:
            response = await client.get(HF_API_URL, params=params)
            response.raise_for_status()
            rows = response.json()
        results = [
            {
                "name": row["id"],
                "description": row.get("pipeline_tag") or "",
                "sizes": [],
                "capabilities": [],
                "downloads": row.get("downloads"),
                "likes": row.get("likes"),
                "tag_count": None,
                "updated": None,
            }
            for row in rows
            if isinstance(row, dict) and valid_hf_repo(str(row.get("id") or "")) and not row.get("private")
        ]
        self._search_cache[key.lower()] = (time.monotonic(), results)
        return results

    async def quantizations(self, repo: str) -> list[dict[str, Any]]:
        """The builds of one repository, each with its size and pull reference."""
        async with self._http() as client:
            response = await client.get(f"{HF_API_URL}/{repo}", params={"blobs": "true"})
            response.raise_for_status()
            detail = response.json()
        siblings = detail.get("siblings") if isinstance(detail, dict) else None
        return gguf_quantizations(siblings if isinstance(siblings, list) else [], repo)
