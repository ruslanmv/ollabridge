"""
Unit tests for the VR Persona Context module.

Lightweight, CI-compatible (no network, no GPU, no external services).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class TestVRPersonaBootstrap:
    """Test VRPersonaBootstrap dataclass."""

    def test_import(self) -> None:
        from ollabridge.connectors.vr_persona_context import VRPersonaBootstrap
        assert VRPersonaBootstrap is not None

    def test_default_values(self) -> None:
        from ollabridge.connectors.vr_persona_context import VRPersonaBootstrap

        b = VRPersonaBootstrap()
        assert b.persona_id == ""
        assert b.supports_vr is True
        assert b.is_vr_ready is False
        assert b.content_rating == "sfw"

    def test_to_dict(self) -> None:
        from ollabridge.connectors.vr_persona_context import VRPersonaBootstrap

        b = VRPersonaBootstrap(persona_id="test", display_name="Test")
        d = b.to_dict()
        assert d["persona_id"] == "test"
        assert d["display_name"] == "Test"
        assert isinstance(d["presence_states"], list)


class TestBuildBootstrapFromProfiles:
    """Test building bootstrap from raw profile dicts."""

    def test_empty_profiles(self) -> None:
        from ollabridge.connectors.vr_persona_context import (
            build_vr_bootstrap_from_profiles,
        )

        b = build_vr_bootstrap_from_profiles(
            persona_agent={"id": "test", "label": "Test", "role": "Tester"},
            manifest={"schema_version": 3},
        )
        assert b.persona_id == "test"
        assert b.display_name == "Test"
        assert b.schema_version == 3
        assert b.is_vr_ready is False  # no vrm_file

    def test_full_v3_profiles(self) -> None:
        from ollabridge.connectors.vr_persona_context import (
            build_vr_bootstrap_from_profiles,
        )

        b = build_vr_bootstrap_from_profiles(
            persona_agent={"id": "scarlett", "label": "Scarlett", "role": "Secretary"},
            manifest={"schema_version": 3},
            cognitive={
                "reasoning_mode": "orchestrated",
                "spatial_intelligence": {"enabled": True},
                "safety_policy": {"content_rating": "sfw"},
            },
            embodiment={
                "expression_style": "moderate",
                "gestures": {"amplitude": "moderate", "talk_style": "presenter", "idle_style": "breathing"},
                "posture": {"default_pose": "standing_formal"},
                "personal_distance": {"default_m": 1.5},
            },
            vr_profile={
                "vrm_binding": {"vrm_file": "scarlett.vrm", "vrm_fallback": "fallback.vrm"},
                "spawn": {"distance_m": 1.8},
                "following": {"enabled": True, "follow_distance_m": 1.8},
                "locomotion_style": "walk",
                "presence_states": ["idle", "speaking", "thinking"],
                "interaction_commands": ["come here", "follow me"],
            },
            voice={"voice_id": "nova", "warmth": 0.4},
            relationship={"relationship_type": "professional"},
        )
        assert b.is_vr_ready is True
        assert b.is_orchestrated is True
        assert b.has_spatial_intelligence is True
        assert b.vrm_file == "scarlett.vrm"
        assert b.voice_id == "nova"
        assert b.spawn_distance_m == 1.8
        assert b.relationship_type == "professional"

    def test_v2_compat_missing_profiles(self) -> None:
        """v2 packages with no v3 profiles should get safe defaults."""
        from ollabridge.connectors.vr_persona_context import (
            build_vr_bootstrap_from_profiles,
        )

        b = build_vr_bootstrap_from_profiles(
            persona_agent={"id": "old_persona", "label": "Old"},
            manifest={"schema_version": 2},
        )
        assert b.schema_version == 2
        assert b.is_vr_ready is False
        assert b.is_orchestrated is False
        assert b.has_spatial_intelligence is False


class TestVRRegistry:
    """Test the in-memory VR persona registry."""

    def test_register_and_get(self) -> None:
        from ollabridge.connectors.vr_persona_context import (
            VRPersonaBootstrap,
            get_vr_persona,
            register_vr_persona,
        )

        b = VRPersonaBootstrap(persona_id="test_reg", display_name="RegTest")
        register_vr_persona("persona:test-reg", b)
        result = get_vr_persona("persona:test-reg")
        assert result is not None
        assert result.persona_id == "test_reg"

    def test_get_missing(self) -> None:
        from ollabridge.connectors.vr_persona_context import get_vr_persona

        assert get_vr_persona("persona:nonexistent") is None

    def test_list_vr_personas(self) -> None:
        from ollabridge.connectors.vr_persona_context import list_vr_personas

        all_personas = list_vr_personas()
        assert isinstance(all_personas, dict)


class TestSuperintelligentPersonasRegistry:
    """Test the built-in superintelligent persona definitions."""

    EXPECTED_MODELS = [
        "persona:scarlett-secretary",
        "persona:milo-friend",
        "persona:nova-collaborator",
        "persona:luna-girlfriend",
        "persona:velvet-companion",
    ]

    def test_all_five_defined(self) -> None:
        from ollabridge.connectors.vr_persona_context import SUPERINTELLIGENT_PERSONAS

        for model in self.EXPECTED_MODELS:
            assert model in SUPERINTELLIGENT_PERSONAS, f"Missing: {model}"

    @pytest.mark.parametrize("model", EXPECTED_MODELS)
    def test_persona_has_required_fields(self, model: str) -> None:
        from ollabridge.connectors.vr_persona_context import SUPERINTELLIGENT_PERSONAS

        p = SUPERINTELLIGENT_PERSONAS[model]
        assert "persona_id" in p
        assert "display_name" in p
        assert "role" in p
        assert "vrm_file" in p
        assert "voice_id" in p
        assert "content_rating" in p
