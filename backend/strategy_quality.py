"""Phase 5 - automatic quality gate for generated strategies (Steps 3 and 4).

The evaluation of Phase 1-4 output showed the same failure modes again and again:
  1. repetitive items       - two selling points / content types that say the same thing
  2. contradictions         - a word is both in `words_to_use` and `words_to_avoid`
  3. invented facts         - percentages / prices that are not in the brief
  4. generic filler         - "game-changer", "cutting-edge", "unlock the power of ..."
  5. not grounded           - nothing in the strategy mentions the actual product
  6. weak call to action    - a paragraph instead of a short action

`quality_issues()` detects them. llm.generate_strategy() feeds the list back to the model for ONE targeted retry
(see llm.py), so a bad first answer costs one extra request instead of a bad result for the user.
"""
from __future__ import annotations

import json
import re

from schemas import CampaignInput, MarketingStrategy

CLICHES = [
    "game-changer", "game changer", "revolutionary", "cutting-edge", "cutting edge", "state-of-the-art",
    "unlock the power", "take it to the next level", "elevate your", "next-level", "world-class", "best-in-class",
]
_STOP = {"the", "and", "for", "with", "that", "this", "your", "from", "have", "into", "about", "more", "than", "their"}


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


def _tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split() if len(t) > 2 and t not in _STOP}


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of the word sets (0..1)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _near_duplicates(items: list[str], threshold: float = 0.75) -> list[tuple[str, str]]:
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _norm(items[i]) == _norm(items[j]) or similarity(items[i], items[j]) >= threshold:
                out.append((items[i], items[j]))
    return out


def quality_issues(strategy: MarketingStrategy, brief: CampaignInput) -> list[str]:
    """Human-readable problems (empty list = good). Written so they can be pasted into a retry prompt."""
    s = strategy
    issues: list[str] = []
    text = json.dumps(s.model_dump(), ensure_ascii=False).lower()
    brief_text = " ".join([brief.product_name, brief.product_description, brief.target_audience]).lower()

    # 1. repetition
    dup = _near_duplicates([f"{p.point} {p.benefit}" for p in s.key_selling_points])
    if dup:
        issues.append(f"key_selling_points repeat each other (e.g. '{dup[0][0][:50]}' vs '{dup[0][1][:50]}'); "
                      "give each point a different angle")
    dup = _near_duplicates([f"{c.type} {c.description}" for c in s.suggested_content_types])
    if dup:
        issues.append(f"suggested_content_types are near-duplicates (e.g. '{dup[0][0][:50]}'); use clearly different formats")
    if len({_norm(m) for m in s.success_metrics}) < len(s.success_metrics):
        issues.append("success_metrics contains duplicates")

    # 2. contradictions
    clash = {_norm(w) for w in s.content_tone.words_to_use} & {_norm(w) for w in s.content_tone.words_to_avoid}
    clash.discard("")
    if clash:
        issues.append(f"words_to_use and words_to_avoid share: {', '.join(sorted(clash)[:3])}")

    # 3. invented statistics / prices
    for m in re.finditer(r"\d+(?:[.,]\d+)?\s?%|[$€£]\s?\d+|\d+x\b", text):
        if m.group(0).replace(" ", "") not in brief_text.replace(" ", ""):
            issues.append(f"contains a number that is not in the brief ('{m.group(0)}'); remove invented statistics, prices and claims")
            break

    # 4. generic filler
    hits = [c for c in CLICHES if c in text]
    if len(hits) >= 2:
        issues.append(f"too many generic buzzwords ({', '.join(hits[:3])}); use concrete, product-specific language")

    # 5. grounding in the actual product
    keywords = {w for w in _tokens(brief.product_description) if len(w) >= 5}
    name = " ".join(_norm(brief.product_name).split())
    ntext = " ".join(_norm(text).split())
    if name not in ntext and not any(k in ntext for k in sorted(keywords)[:40]):
        issues.append("the strategy never mentions the product or its real features; ground every section in the brief")

    # 6. call to action
    cta = s.call_to_action.primary.strip()
    if len(cta.split()) > 9:
        issues.append("call_to_action.primary is too long; use a short imperative (max 6 words)")
    if _norm(cta) in {_norm(a) for a in s.call_to_action.alternatives}:
        issues.append("call_to_action.alternatives repeats the primary CTA")

    return issues[:4]
