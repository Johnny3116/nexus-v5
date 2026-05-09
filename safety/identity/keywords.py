"""Keyword dictionary + category→expression mapping for Soul v1.

Categories are the Soul's internal emotion taxonomy (joy/fun/angry/sorrow).
EXPRESSION_MAP translates those to the existing VRM expression presets
defined in nexus_vtube.avatar.expression_controller.EXPRESSION_PRESETS.

Tie-break order in PRIORITY: negative emotions win over positive when hit
counts are equal (angry > sorrow > joy > fun). Rationale: missing a joyful
reaction is less jarring than missing an angry one.
"""

from __future__ import annotations

KEYWORDS: dict[str, list[str]] = {
    "joy": [
        "happy", "happiness", "happily", "great", "love", "awesome",
        "wonderful", "excited", "glad", "yay", "perfect", "amazing",
        "delighted", "thrilled", "fantastic",
    ],
    "fun": [
        "lol", "haha", "funny", "hilarious", "lmao", "rofl",
        "silly", "playful", "joke", "jk", "lmfao",
    ],
    "angry": [
        "angry", "hate", "furious", "pissed", "mad", "rage",
        "annoyed", "frustrated", "damn", "fuck", "terrible",
        "awful", "disgusting", "stupid",
    ],
    "sorrow": [
        "sad", "sorry", "loss", "lost", "miss", "lonely",
        "hurt", "pain", "crying", "tears", "grief", "depressed",
        "heartbroken", "mourn",
    ],
}

# Tie-break ordering: earlier entries win on equal hit counts.
PRIORITY: list[str] = ["angry", "sorrow", "joy", "fun"]

# Soul category → three-vrm@3 normalized expression preset name.
#
# The target names below must all exist in
# nexus_vtube.avatar.expression_controller.EXPRESSION_PRESETS AND correspond
# to a real VRM 0.x preset binding on the target avatar (NexusArachneAvatar
# is VRM 0.x — confirmed via audit 2026-04-10).
#
# CRITICAL: VRM 0.x has no "surprised" preset. Mapping `fun → surprised`
# produced silent no-ops. The correct three-vrm@3 name for VRM 0.x `fun` is
# `relaxed`. See expression_controller.py docstring for the full name table.
EXPRESSION_MAP: dict[str, str] = {
    "joy":     "happy",    # three-vrm@3 'happy' ← VRM 0.x 'joy' (Face morph 33)
    "fun":     "relaxed",  # three-vrm@3 'relaxed' ← VRM 0.x 'fun' (Face morph 32)
    "angry":   "angry",
    "sorrow":  "sad",      # three-vrm@3 'sad' ← VRM 0.x 'sorrow' (Face morphs 34 + 9)
    "neutral": "neutral",
}
