"""
Fit Conversation intake — turn a warm, free-text chat into a structured StyleProfile.

The conversation and the extraction are a language-model job (Claude). This module keeps
the DETERMINISTIC seam: the extraction schema, the stylist system prompt, and a pluggable
`extractor` interface, so the whole flow is testable offline with a stub and NO API spend.
The live Claude adapter is defined but intentionally NOT invoked here — wiring it needs a
model choice (cost) and an explicit go-ahead (money guardrail).

Contract: an `extractor` is `Callable[[list[dict]], dict]` — it takes chat messages
[{role, content}] and returns a raw StyleProfile-shaped dict; `extract_style_profile`
normalises that through `style_profile.assemble_style_profile`. Swap the stub for the
Claude adapter without touching callers.

Privacy: the raw conversation is sensitive (people share insecurities). Derive-and-discard
— extract the compact profile, then drop the transcript; never persist the free text, and
never surface `sensitivities` back to the user.
"""
from __future__ import annotations
from typing import Callable, List, Mapping
from app.style_profile import assemble_style_profile

Extractor = Callable[[List[dict]], dict]

# Warm, non-judgemental stylist persona. Kept here so the wiring is ready; not sent until
# the live adapter is switched on (with a chosen model).
STYLIST_SYSTEM_PROMPT = (
    "You are a warm, encouraging personal stylist helping someone dress in a way that "
    "makes them feel confident. Ask a few short, friendly questions — never clinical, "
    "never about weight or numbers. Invite them to say how they like clothes to feel and "
    "what they'd rather play up or play down, in their own words. Make them feel safe to "
    "share. Do not repeat back anything they seem self-conscious about; simply use it to "
    "dress them well. When you have enough, produce a StyleProfile."
)

# JSON schema for Claude structured outputs (output_config.format). The live adapter
# passes this so the model returns a StyleProfile-shaped object, not prose.
STYLE_PROFILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "fit_feel": {"type": "string", "enum": ["fitted", "true", "relaxed", "oversized"]},
        "region_preferences": {
            "type": "object",
            "description": "body area -> how it should sit (waist, chest, shoulder, hip, "
                           "thigh, bicep, forearm)",
            "additionalProperties": {"type": "string",
                                     "enum": ["fitted", "true", "relaxed", "oversized"]},
        },
        "comfort_offset": {
            "type": "object",
            "description": "clothing category -> sizes up/down from measured (top, bottom)",
            "additionalProperties": {"type": "integer"},
        },
        "sensitivities": {"type": "array", "items": {"type": "string"},
                          "description": "PRIVATE — areas to flatter; never shown to the user"},
        "confidence_notes": {"type": "array", "items": {"type": "string"},
                             "description": "what makes them feel good (e.g. structured shoulders)"},
    },
    "required": ["fit_feel"],
}


def extract_style_profile(messages: List[Mapping], extractor: Extractor,
                          source: str = "conversation") -> dict:
    """Run the injected extractor over the chat and normalise to a StyleProfile."""
    raw = extractor([dict(m) for m in messages]) or {}
    return assemble_style_profile(
        fit_feel=raw.get("fit_feel"),
        region_preferences=raw.get("region_preferences"),
        comfort_offset=raw.get("comfort_offset"),
        sensitivities=raw.get("sensitivities"),
        confidence_notes=raw.get("confidence_notes"),
        source=source,
    )


def keyword_stub_extractor(messages: List[Mapping]) -> dict:
    """
    Deterministic, offline extractor for tests and local dev — NO model, NO spend. Scans
    the user's words for a few obvious cues. It is intentionally simple: the real signal
    quality comes from the Claude adapter; this only proves the seam end-to-end.
    """
    text = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "user").lower()
    prof: dict = {"region_preferences": {}, "sensitivities": [], "confidence_notes": []}
    if any(w in text for w in ("loose", "relaxed", "roomy", "comfortable", "baggy")):
        prof["fit_feel"] = "oversized" if "baggy" in text else "relaxed"
    elif any(w in text for w in ("fitted", "snug", "slim")):
        prof["fit_feel"] = "fitted"
    else:
        prof["fit_feel"] = "true"
    for word, areas in (("belly", ("waist",)), ("tummy", ("waist",)), ("waist", ("waist",)),
                        ("chest", ("chest",)), ("midsection", ("waist", "chest")),
                        ("arms", ("bicep",)), ("thighs", ("thigh",))):
        if word in text and any(w in text for w in ("hide", "fat", "conscious", "cover", "insecure", "filled")):
            prof["sensitivities"].append("midsection" if word in ("belly", "tummy") else word)
            for a in areas:
                prof["region_preferences"][a] = "relaxed"
    if "shoulder" in text and any(w in text for w in ("show", "structured", "broad", "proud")):
        prof["confidence_notes"].append("structured shoulders")
        prof["region_preferences"]["shoulder"] = "true"
    return prof


def claude_extractor_stub(messages: List[Mapping]) -> dict:
    """
    NOT WIRED. Placeholder documenting the live adapter. When switched on it will call
    Claude via the Anthropic SDK with STYLIST_SYSTEM_PROMPT and structured outputs
    (output_config.format = {type: json_schema, schema: STYLE_PROFILE_SCHEMA}), model TBD
    (a smaller model likely suffices for cost). Raising keeps it from being used by
    accident and from spending money silently.
    """
    raise NotImplementedError(
        "Live Claude extraction is not wired: choose a model (cost) and enable API calls first.")
