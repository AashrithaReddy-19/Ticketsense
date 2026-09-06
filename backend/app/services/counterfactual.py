"""Deterministic counterfactual explanations for resolution-policy decisions.

Every sentence here is generated from gate codes, scores, thresholds and
detail strings that were already computed and stored by
``resolution_policy.py`` at decision time — nothing is inferred from a
model's chain-of-thought, and nothing is invented. The two things this
module refuses to do, by construction:

1. Tell anyone how to make a failing gate pass other than by genuinely
   satisfying it (more/better approved evidence, higher classification
   confidence, etc.) — never "how to bypass" or "how to lower the bar".
2. Imply a fixed, policy-level restriction (a sensitive category, an
   urgent ticket, a disabled policy) could ever be satisfied by evidence.
   Those gates are always described as requiring a human, full stop.
"""
from dataclasses import dataclass

EXPLANATION_VERSION = "counterfactual-v1"

# Fixed policy/business restrictions: no amount of additional evidence changes
# these. Every other gate is evidence/quality-dependent for this specific
# ticket and could, in principle, be satisfied by better evidence.
IMMUTABLE_GATES = {
    "policy_enabled", "category_allowlisted", "category_not_sensitive",
    "not_critical", "no_immediate_repeat",
}

GATE_LABELS = {
    "policy_enabled": "An active resolution policy must be enabled for this department",
    "category_allowlisted": "The category must be on the automatic-resolution allowlist",
    "category_not_sensitive": "Sensitive categories (payments, security, data loss, access control, legal/compliance) always require a human",
    "not_critical": "Urgent-priority tickets always require a human",
    "no_immediate_repeat": "A previously-rejected answer cannot immediately auto-publish again",
    "overall_confidence": "Overall confidence",
    "classification_confidence": "Classification confidence",
    "classification_margin": "Classification margin between the top two categories",
    "approved_current_evidence": "At least one approved, current evidence source",
    "retrieval_relevance": "Retrieval relevance of the best matching evidence",
    "citation_validation": "Every cited source must independently validate",
    "citation_coverage": "Citation coverage",
    "claim_grounding": "Every claim in the draft must be grounded in approved evidence",
    "no_contradiction": "The evidence must not contain contradictory guidance",
    "pii_secrets": "The ticket or draft must not contain detected personal data or secrets",
    "attachment_quality": "Extracted attachment content must meet a minimum confidence",
    "pipeline_complete": "The AI processing pipeline must have completed without a fallback",
    "immutable_response_available": "A cited draft response must exist before publication",
    "playbook_compatible": "The response must match an approved playbook when one applies",
}


@dataclass(frozen=True)
class GateOutcome:
    code: str
    category: str  # "immutable" | "evidence"
    label: str
    passed: bool
    score: float | None
    threshold: float | None
    detail: str | None
    narrative: str


def _classify(code: str) -> str:
    return "immutable" if code in IMMUTABLE_GATES else "evidence"


def _describe_gap(code: str, score: float | None, threshold: float | None, detail: str | None) -> str:
    label = GATE_LABELS.get(code, code.replace("_", " "))
    if score is not None and threshold is not None:
        gap = threshold - score
        if gap > 0:
            return f"{label} was {score:.0%}, below the required {threshold:.0%}."
        return f"{label} was {score:.0%}, meeting the required {threshold:.0%}."
    if detail:
        return f"{label}: {detail}."
    return f"{label} did not pass."


def _minimal_change(code: str, score: float | None, threshold: float | None) -> str | None:
    """A single sentence describing what satisfying this gate would look
    like — always framed as genuinely meeting the requirement, never as a
    way to work around it."""
    if score is None or threshold is None or score >= threshold:
        return None
    if code == "citation_coverage":
        return "An additional approved source covering the uncited claims would satisfy this gate."
    if code == "retrieval_relevance":
        return f"An additional approved source with similarity >= {threshold:.2f} would satisfy the evidence requirement."
    if code == "overall_confidence":
        return "Higher independently-calibrated confidence — from stronger evidence or a clearer classification — would satisfy this gate."
    if code == "classification_confidence":
        return "A clearer, less ambiguous ticket description would raise classification confidence."
    if code == "classification_margin":
        return "A ticket description that maps more clearly to a single category would widen this margin."
    if code == "approved_current_evidence":
        return "At least one approved, current knowledge article for this exact scope would satisfy this gate."
    return None


def build_explanation(passed_gates: list[str], failed_gates: list[str], factors: dict) -> dict:
    """Pure function: gate codes + stored factors in, a structured
    explanation out. No I/O, fully deterministic given its inputs — the
    router persists the result alongside these exact inputs for later
    reproducibility."""
    outcomes: list[GateOutcome] = []
    for code in failed_gates:
        factor = factors.get(code, {})
        score, threshold, detail = factor.get("score"), factor.get("threshold"), factor.get("detail")
        outcomes.append(GateOutcome(
            code=code, category=_classify(code), label=GATE_LABELS.get(code, code.replace("_", " ")),
            passed=False, score=score, threshold=threshold, detail=detail,
            narrative=_describe_gap(code, score, threshold, detail),
        ))

    immutable_failures = [o for o in outcomes if o.category == "immutable"]
    evidence_failures = [o for o in outcomes if o.category == "evidence"]

    evidence_gaps = []
    for outcome in evidence_failures:
        change = _minimal_change(outcome.code, outcome.score, outcome.threshold)
        evidence_gaps.append({
            "code": outcome.code, "narrative": outcome.narrative,
            "minimal_safe_change": change,
        })

    if not failed_gates:
        narrative_internal = f"All {len(passed_gates)} safety gates passed; no human review was required for this decision."
        narrative_customer = "Your resolution passed every automated safety check."
    elif immutable_failures:
        reasons = "; ".join(o.narrative for o in immutable_failures)
        if evidence_failures:
            narrative_internal = (
                f"This ticket requires human review regardless of confidence: {reasons} "
                f"Even if the {len(evidence_failures)} evidence/quality gate(s) below were fully satisfied, "
                f"this ticket would still be blocked by the fixed policy restriction(s) above."
            )
        else:
            narrative_internal = f"This ticket requires human review regardless of confidence: {reasons}"
        narrative_customer = "This ticket involves a category that always receives a human review, regardless of how confident the automated system is."
    else:
        reasons = " ".join(o.narrative for o in evidence_failures)
        narrative_internal = f"Human assistance is required because the following evidence/quality gate(s) did not pass: {reasons}"
        narrative_customer = "Your ticket needs a quick review by our support team to confirm the answer is accurate before it's shared with you."

    return {
        "explanation_version": EXPLANATION_VERSION,
        "blocking_gates": [
            {"code": o.code, "category": o.category, "label": o.label, "score": o.score, "threshold": o.threshold, "detail": o.detail, "narrative": o.narrative}
            for o in outcomes
        ],
        "immutable_reasons": [o.narrative for o in immutable_failures],
        "evidence_gaps": evidence_gaps,
        "narrative_internal": narrative_internal,
        "narrative_customer": narrative_customer,
    }
