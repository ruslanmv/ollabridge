"""
VR Persona Context — enriches persona context with v3 VR/embodiment data.

Additive module: does not modify any existing OllaBridge code.
Fetches the v3 persona profiles (cognitive, embodiment, VR, voice,
relationship) from HomePilot and exposes them to VR clients via a
lightweight dataclass.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VRPersonaBootstrap:
    """Lightweight VR bootstrap payload (~1KB) sent to the 3D client."""

    persona_id: str = ""
    display_name: str = ""
    role: str = ""
    schema_version: int = 2

    # Voice hints for TTS
    voice_id: str = ""
    voice_provider: str = "auto"
    pitch_bias: float = 0.0
    rate_bias: float = 0.0
    pause_style: str = "natural"
    warmth: float = 0.5

    # VR binding
    vrm_file: str = ""
    vrm_fallback: str = ""
    avatar_scale: float = 1.0
    avatar_gender_hint: str = "neutral"

    # Spawn
    spawn_distance_m: float = 1.5
    spawn_angle_deg: float = 0.0

    # Following
    follow_enabled: bool = True
    follow_distance_m: float = 1.5
    follow_side: str = "adaptive"

    # Navigation
    locomotion_style: str = "walk"
    walk_speed_mps: float = 1.2

    # Embodiment
    expression_style: str = "moderate"
    gesture_amplitude: str = "moderate"
    talk_style: str = "subtle_nod"
    idle_style: str = "breathing"
    default_pose: str = "standing_relaxed"
    personal_distance_m: float = 1.2

    # Interaction
    presence_states: List[str] = field(default_factory=lambda: [
        "idle", "listening", "thinking", "speaking",
    ])
    interaction_commands: List[str] = field(default_factory=lambda: [
        "come here", "follow me", "stop", "sit down",
        "stand up", "look at me",
    ])

    # Relationship hints for behavior
    relationship_type: str = "professional"
    emotional_continuity: bool = False
    formality: str = "casual"

    # Capabilities
    is_vr_ready: bool = False
    is_orchestrated: bool = False
    has_spatial_intelligence: bool = False
    content_rating: str = "sfw"

    # Comfort limits
    min_distance_m: float = 0.3
    max_distance_m: float = 10.0

    # XR preferences
    supports_vr: bool = True
    supports_ar: bool = False
    supports_passthrough: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_vr_bootstrap_from_profiles(
    persona_agent: Dict[str, Any],
    manifest: Dict[str, Any],
    cognitive: Optional[Dict[str, Any]] = None,
    embodiment: Optional[Dict[str, Any]] = None,
    vr_profile: Optional[Dict[str, Any]] = None,
    voice: Optional[Dict[str, Any]] = None,
    relationship: Optional[Dict[str, Any]] = None,
) -> VRPersonaBootstrap:
    """Build a VRPersonaBootstrap from raw persona profile dicts.

    Gracefully handles missing profiles (v2 packages) by using defaults.
    """
    cognitive = cognitive or {}
    embodiment = embodiment or {}
    vr_profile = vr_profile or {}
    voice = voice or {}
    relationship = relationship or {}

    vrm = vr_profile.get("vrm_binding", {})
    spawn = vr_profile.get("spawn", {})
    follow = vr_profile.get("following", {})
    nav = vr_profile.get("navigation", {})
    look = embodiment.get("look_at", {})
    gest = embodiment.get("gestures", {})
    posture = embodiment.get("posture", {})
    dist = embodiment.get("personal_distance", {})
    comfort = vr_profile.get("comfort_limits", {})
    xr = vr_profile.get("xr_preferences", {})
    safety = cognitive.get("safety_policy", {})
    spatial = cognitive.get("spatial_intelligence", {})

    return VRPersonaBootstrap(
        persona_id=persona_agent.get("id", ""),
        display_name=persona_agent.get("label", ""),
        role=persona_agent.get("role", ""),
        schema_version=manifest.get("schema_version", 2),
        # Voice
        voice_id=voice.get("voice_id", ""),
        voice_provider=voice.get("voice_provider", "auto"),
        pitch_bias=voice.get("pitch_bias", 0.0),
        rate_bias=voice.get("rate_bias", 0.0),
        pause_style=voice.get("pause_style", "natural"),
        warmth=voice.get("warmth", 0.5),
        # VRM
        vrm_file=vrm.get("vrm_file", ""),
        vrm_fallback=vrm.get("vrm_fallback", ""),
        avatar_scale=vrm.get("avatar_scale", 1.0),
        avatar_gender_hint=vrm.get("avatar_gender_hint", "neutral"),
        # Spawn
        spawn_distance_m=spawn.get("distance_m", 1.5),
        spawn_angle_deg=spawn.get("angle_deg", 0.0),
        # Following
        follow_enabled=follow.get("enabled", True),
        follow_distance_m=follow.get("follow_distance_m", 1.5),
        follow_side=follow.get("follow_side", "adaptive"),
        # Navigation
        locomotion_style=vr_profile.get("locomotion_style", "walk"),
        walk_speed_mps=nav.get("walk_speed_mps", 1.2),
        # Embodiment
        expression_style=embodiment.get("expression_style", "moderate"),
        gesture_amplitude=gest.get("amplitude", "moderate"),
        talk_style=gest.get("talk_style", "subtle_nod"),
        idle_style=gest.get("idle_style", "breathing"),
        default_pose=posture.get("default_pose", "standing_relaxed"),
        personal_distance_m=dist.get("default_m", 1.2),
        # Interaction
        presence_states=vr_profile.get("presence_states", [
            "idle", "listening", "thinking", "speaking",
        ]),
        interaction_commands=vr_profile.get("interaction_commands", [
            "come here", "follow me", "stop", "sit down",
            "stand up", "look at me",
        ]),
        # Relationship
        relationship_type=relationship.get("relationship_type", "professional"),
        emotional_continuity=relationship.get("emotional_continuity", False),
        formality=relationship.get("formality", "casual"),
        # Capabilities
        is_vr_ready=bool(vrm.get("vrm_file")),
        is_orchestrated=cognitive.get("reasoning_mode") == "orchestrated",
        has_spatial_intelligence=spatial.get("enabled", False),
        content_rating=safety.get("content_rating", "sfw"),
        # Comfort
        min_distance_m=comfort.get("min_distance_m", 0.3),
        max_distance_m=comfort.get("max_distance_m", 10.0),
        # XR
        supports_vr=xr.get("supports_vr", True),
        supports_ar=xr.get("supports_ar", False),
        supports_passthrough=xr.get("supports_passthrough", False),
    )


# ── Persona model → VR profile registry (in-memory) ──────────────────

_VR_REGISTRY: Dict[str, VRPersonaBootstrap] = {}


def register_vr_persona(model_name: str, bootstrap: VRPersonaBootstrap) -> None:
    """Register a VR persona bootstrap for a model name."""
    _VR_REGISTRY[model_name] = bootstrap


def get_vr_persona(model_name: str) -> Optional[VRPersonaBootstrap]:
    """Retrieve the VR bootstrap for a model, or None."""
    return _VR_REGISTRY.get(model_name)


def list_vr_personas() -> Dict[str, VRPersonaBootstrap]:
    """Return all registered VR persona bootstraps."""
    return dict(_VR_REGISTRY)


# ── Built-in v3 persona registry (the five superintelligent personas) ──

SUPERINTELLIGENT_PERSONAS: Dict[str, Dict[str, Any]] = {
    "persona:scarlett-secretary": {
        "persona_id": "scarlett_secretary",
        "display_name": "Scarlett",
        "role": "Executive Secretary",
        "vrm_file": "scarlett_secretary.vrm",
        "vrm_fallback": "AvatarSample_A.vrm",
        "voice_id": "nova",
        "motion_profile": "professional_assistant",
        "xr_profile": "office_companion",
        "content_rating": "sfw",
    },
    "persona:milo-friend": {
        "persona_id": "milo_friend",
        "display_name": "Milo",
        "role": "Best Friend",
        "vrm_file": "milo_friend.vrm",
        "vrm_fallback": "AvatarSample_B.vrm",
        "voice_id": "echo",
        "motion_profile": "casual_friend",
        "xr_profile": "social_companion",
        "content_rating": "sfw",
    },
    "persona:nova-collaborator": {
        "persona_id": "nova_collaborator",
        "display_name": "Nova",
        "role": "Work Collaborator",
        "vrm_file": "nova_collaborator.vrm",
        "vrm_fallback": "fem_vroid.vrm",
        "voice_id": "shimmer",
        "motion_profile": "focused_collaborator",
        "xr_profile": "office_companion",
        "content_rating": "sfw",
    },
    "persona:luna-girlfriend": {
        "persona_id": "luna_girlfriend",
        "display_name": "Luna",
        "role": "Girlfriend Companion",
        "vrm_file": "luna_girlfriend.vrm",
        "vrm_fallback": "fem_vroid.vrm",
        "voice_id": "alloy",
        "motion_profile": "intimate_companion",
        "xr_profile": "home_companion",
        "content_rating": "mature",
    },
    "persona:velvet-companion": {
        "persona_id": "velvet_companion",
        "display_name": "Velvet",
        "role": "Adult Companion",
        "vrm_file": "velvet_companion.vrm",
        "vrm_fallback": "AvatarSample_A.vrm",
        "voice_id": "fable",
        "motion_profile": "intimate_companion",
        "xr_profile": "home_companion",
        "content_rating": "adult",
    },
}
