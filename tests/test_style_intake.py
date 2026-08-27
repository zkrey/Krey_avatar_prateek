"""
Verification of the Fit Conversation intake seam — the stub extractor and normalisation.
No model, no API spend (the live Claude adapter is intentionally not invoked).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app import style_intake as si


def test_stub_extracts_the_founders_own_words():
    # the exact kind of thing a user types.
    chat = [{"role": "user",
             "content": "I usually wear L on top because my chest and waist are filled with "
                        "fat and I'm a bit conscious of it. I like my shoulders to show though."}]
    prof = si.extract_style_profile(chat, si.keyword_stub_extractor)
    assert {"waist", "chest"} & set(prof["sensitivities"])       # midsection captured
    assert prof["region_preferences"].get("waist") == "relaxed"
    assert prof["region_preferences"].get("chest") == "relaxed"
    assert prof["region_preferences"].get("shoulder") == "true"
    assert "structured shoulders" in prof["confidence_notes"]
    assert prof["source"] == "conversation"


def test_stub_defaults_to_true_when_no_cues():
    prof = si.extract_style_profile([{"role": "user", "content": "hi"}], si.keyword_stub_extractor)
    assert prof["fit_feel"] == "true" and prof["sensitivities"] == []


def test_relaxed_preference_detected():
    prof = si.extract_style_profile(
        [{"role": "user", "content": "I like everything loose and comfortable"}],
        si.keyword_stub_extractor)
    assert prof["fit_feel"] == "relaxed"


def test_schema_and_prompt_are_ready_for_the_live_adapter():
    assert si.STYLE_PROFILE_SCHEMA["required"] == ["fit_feel"]
    assert si.STYLE_PROFILE_SCHEMA["additionalProperties"] is False
    assert "stylist" in si.STYLIST_SYSTEM_PROMPT.lower()


def test_live_adapter_is_not_wired_and_refuses_to_spend():
    with pytest.raises(NotImplementedError):
        si.claude_extractor_stub([{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
