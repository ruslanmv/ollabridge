"""Memory Bridge — fetches lightweight persona context from HomePilot.

This module provides a non-destructive, additive layer that allows OllaBridge
to fetch essential persona memory (user facts, preferences, voice style,
emotional base) from HomePilot and relay it to downstream clients like the
3D-Avatar-Chatbot.

The bridge only reads from HomePilot — it never writes or modifies any
persona state.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


@dataclass(frozen=True)
class PersonaContext:
    """Lightweight persona context for downstream clients (~200-500 bytes).

    Contains only the *essential* information a client (e.g. 3D avatar)
    needs to personalise the interaction — voice parameters, emotional
    baseline, user facts.  Everything else stays server-side in HomePilot.
    """

    persona_id: str = ""
    label: str = ""

    # Voice style for TTS tuning
    voice_rate_bias: float = 1.0
    voice_pitch_bias: float = 1.0
    voice_pause_style: str = "natural"

    # Response style
    response_max_length: str = "medium"
    response_tone: str = "neutral"
    response_use_emoji: bool = False

    # Conversation dynamics
    emotional_base: str = "neutral"
    initiative: str = "balanced"

    # Safety
    requires_adult_gate: bool = False
    allow_explicit: bool = False

    # User facts from long-term memory (key→value)
    user_facts: dict[str, str] = field(default_factory=dict)

    # User preferences from long-term memory
    user_preferences: dict[str, str] = field(default_factory=dict)

    # Image style hint (for avatar rendering decisions)
    image_style_hint: str = ""

    # --- Phase 7: VR-safe bootstrap metadata ---
    display_name: str = ""
    short_bio: str = ""
    voice_hints: str = ""               # e.g. "female,warm,English"
    supported_directives: list[str] = field(default_factory=list)  # e.g. ["emotion","pose"]
    default_avatar_mood: str = ""       # e.g. "happy", "calm"
    image_support: bool = False         # persona has images available
    default_appearance_url: str = ""    # preview image URL

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "persona_id": self.persona_id,
            "label": self.label,
            "voice": {
                "rate_bias": self.voice_rate_bias,
                "pitch_bias": self.voice_pitch_bias,
                "pause_style": self.voice_pause_style,
            },
            "response": {
                "max_length": self.response_max_length,
                "tone": self.response_tone,
                "use_emoji": self.response_use_emoji,
            },
            "dynamics": {
                "emotional_base": self.emotional_base,
                "initiative": self.initiative,
            },
            "safety": {
                "requires_adult_gate": self.requires_adult_gate,
                "allow_explicit": self.allow_explicit,
            },
        }
        if self.user_facts:
            d["user_facts"] = self.user_facts
        if self.user_preferences:
            d["user_preferences"] = self.user_preferences
        if self.image_style_hint:
            d["image_style_hint"] = self.image_style_hint

        # Phase 7: VR bootstrap metadata
        d["vr_bootstrap"] = {
            "display_name": self.display_name or self.label,
            "short_bio": self.short_bio,
            "voice_hints": self.voice_hints,
            "supported_directives": self.supported_directives,
            "default_avatar_mood": self.default_avatar_mood or self.emotional_base,
            "image_support": self.image_support,
            "default_appearance_url": self.default_appearance_url,
        }
        return d


# ---------------------------------------------------------------------------
# Cache — avoids hitting HomePilot on every single chat request
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    context: PersonaContext
    fetched_at: float


class MemoryBridge:
    """Fetches persona context from a HomePilot backend.

    * Read-only — never modifies HomePilot state.
    * Cached — avoids repeated round-trips (default TTL 60 s).
    * Graceful — returns empty context on any failure (never blocks chat).
    """

    def __init__(self, *, cache_ttl_seconds: float = 60.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
        )
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl_seconds

    async def aclose(self) -> None:
        await self._client.aclose()

    # ----- public API -----

    async def fetch_context(
        self,
        *,
        base: str,
        model: str,
        api_key: str = "",
        project_id: Optional[str] = None,
    ) -> PersonaContext:
        """Return lightweight persona context for *model*.

        *model* can be:
          - ``persona:<project_id>``   → custom persona project
          - ``personality:<agent_id>`` → built-in personality

        If *project_id* is given explicitly it takes precedence.

        The result is cached for ``cache_ttl_seconds`` to avoid
        hammering HomePilot on every chat turn.
        """
        cache_key = f"{base}|{model}|{project_id or ''}"
        now = time.monotonic()

        cached = self._cache.get(cache_key)
        if cached and (now - cached.fetched_at) < self._cache_ttl:
            return cached.context

        try:
            ctx = await self._fetch(
                base=base,
                model=model,
                api_key=api_key,
                project_id=project_id,
            )
        except Exception:
            # Never let a memory-bridge failure block chat.
            ctx = PersonaContext(persona_id=model)

        self._cache[cache_key] = _CacheEntry(context=ctx, fetched_at=now)
        return ctx

    def invalidate(self, *, model: str = "", base: str = "") -> None:
        """Drop cached entries (optionally filtered)."""
        if not model and not base:
            self._cache.clear()
            return
        keys = [
            k for k in self._cache
            if (not model or model in k) and (not base or base in k)
        ]
        for k in keys:
            del self._cache[k]

    # ----- internals -----

    def _headers(self, api_key: str) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            h["Authorization"] = f"Bearer {api_key}"
            h["X-API-Key"] = api_key
        return h

    async def _fetch(
        self,
        *,
        base: str,
        model: str,
        api_key: str,
        project_id: Optional[str],
    ) -> PersonaContext:
        """Fetch personality definition + long-term memory from HomePilot."""
        base = base.rstrip("/")
        headers = self._headers(api_key)

        # ---- Resolve IDs from model string ----
        personality_id: Optional[str] = None
        pid = project_id

        if model.startswith("persona:"):
            pid = pid or model.split(":", 1)[1]
        elif model.startswith("personality:"):
            personality_id = model.split(":", 1)[1]

        # ---- 1. Fetch personality definition ----
        agent_data: dict[str, Any] = {}
        if personality_id:
            try:
                resp = await self._client.get(
                    f"{base}/api/personalities/{personality_id}",
                    headers=headers,
                )
                if resp.status_code == 200:
                    agent_data = resp.json()
            except Exception:
                pass

        # ---- 2. Fetch long-term memory (facts + preferences) ----
        user_facts: dict[str, str] = {}
        user_prefs: dict[str, str] = {}

        if pid:
            for category, target in [("fact", user_facts), ("preference", user_prefs)]:
                try:
                    resp = await self._client.get(
                        f"{base}/persona/memory",
                        params={"project_id": pid, "category": category},
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        body = resp.json()
                        for mem in body.get("memories", []):
                            key = mem.get("key", "")
                            val = mem.get("value", "")
                            if key and val:
                                target[key] = val
                except Exception:
                    pass

        # ---- Build context ----
        voice = agent_data.get("voice_style", {}) or {}
        resp_style = agent_data.get("response_style", {}) or {}
        dynamics = agent_data.get("dynamics", {}) or {}
        safety = agent_data.get("safety", {}) or {}

        # Phase 7: Extract VR bootstrap metadata
        display_name = agent_data.get("label", "") or agent_data.get("display_name", "")
        short_bio = agent_data.get("short_bio", "") or agent_data.get("goal", "")
        emotional_base_str = str(dynamics.get("emotional_base", "neutral"))

        # Determine image support from appearance data
        appearance = agent_data.get("persona_appearance", {}) or {}
        has_images = bool(
            appearance.get("selected_filename")
            or appearance.get("sets")
            or appearance.get("outfits")
        )
        default_img = ""
        sel_file = appearance.get("selected_filename", "")
        if sel_file:
            default_img = f"/files/{sel_file}"

        return PersonaContext(
            persona_id=personality_id or pid or model,
            label=agent_data.get("label", ""),
            voice_rate_bias=float(voice.get("rate_bias", 1.0)),
            voice_pitch_bias=float(voice.get("pitch_bias", 1.0)),
            voice_pause_style=str(voice.get("pause_style", "natural")),
            response_max_length=str(resp_style.get("max_length", "medium")),
            response_tone=str(resp_style.get("tone", "neutral")),
            response_use_emoji=bool(resp_style.get("use_emoji", False)),
            emotional_base=emotional_base_str,
            initiative=str(dynamics.get("initiative", "balanced")),
            requires_adult_gate=bool(safety.get("requires_adult_gate", False)),
            allow_explicit=bool(safety.get("allow_explicit", False)),
            user_facts=user_facts,
            user_preferences=user_prefs,
            image_style_hint=str(agent_data.get("image_style_hint", "") or ""),
            # Phase 7 fields
            display_name=display_name,
            short_bio=short_bio,
            voice_hints=str(voice.get("hints", "")),
            supported_directives=["emotion", "pose"],
            default_avatar_mood=emotional_base_str,
            image_support=has_images,
            default_appearance_url=default_img,
        )
