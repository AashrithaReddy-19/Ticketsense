"""Conservative deterministic claim/evidence validator; not a perfect fact checker."""
import re

VALIDATOR_VERSION = "deterministic-grounding-1.0"
UNSAFE = re.compile(r"\b(?:disable (?:the )?(?:firewall|antivirus)|delete all|format (?:the )?disk|rm -rf|share (?:your )?password)\b", re.I)
OVERSTATED_CERTAINTY = re.compile(r"\b(?:definitely|certainly|guaranteed|always fixes|cannot fail)\b", re.I)


def validate_grounding(draft: str, evidence: list[dict], citation_validation: dict) -> dict:
    evidence_by_id = {item.get("citation_id"): item for item in evidence}
    contradictions=[]
    conflict_pairs=(("enable","disable"),("required","prohibited"),("supported","unsupported"))
    lowered=[(item.get("citation_id"),item.get("chunk_text","").lower()) for item in evidence]
    for index,(left_id,left) in enumerate(lowered):
        for right_id,right in lowered[index+1:]:
            shared=set(re.findall(r"[a-z0-9-]{5,}",left))&set(re.findall(r"[a-z0-9-]{5,}",right))
            for positive,negative in conflict_pairs:
                if len(shared)>=2 and ((positive in left and negative in right) or (negative in left and positive in right)):
                    contradictions.append({"left_citation":left_id,"right_citation":right_id,"terms":[positive,negative]})
    claims = []
    invalid_citations=set(citation_validation.get("invalid_citation_ids",[]))
    # Providers conventionally place the citation after sentence punctuation.
    # Split after the citation/newline so it remains attached to the claim it supports.
    for raw in re.split(r"\n+|(?<=\])\s+(?=[A-Z])", draft or ""):
        claim = raw.strip()
        if not claim: continue
        cited = re.findall(r"\[((?:KB|RT)-\d{3})\]", claim)
        citation_id = cited[0] if cited else None
        source = evidence_by_id.get(citation_id) if citation_id else None
        clean = re.sub(r"\[(?:KB|RT)-\d{3}\]", "", claim).strip()
        claim_terms = {x.lower() for x in re.findall(r"[A-Za-z0-9-]{4,}", clean)}
        evidence_terms = {x.lower() for x in re.findall(r"[A-Za-z0-9-]{4,}", source.get("chunk_text", ""))} if source else set()
        overlap = len(claim_terms & evidence_terms) / max(1, len(claim_terms))
        direct_conflict=False
        if source:
            source_text=source.get("chunk_text","").lower();claim_text=clean.lower()
            direct_conflict=any((positive in claim_text and negative in source_text) or (negative in claim_text and positive in source_text) for positive,negative in conflict_pairs)
        if UNSAFE.search(clean): status, risk, reason = "Unsupported", "critical", "Potentially destructive instruction requires human investigation"
        elif not citation_id: status, risk, reason = "Not Verifiable", "medium", "Claim has no evidence citation"
        elif not source: status, risk, reason = "Unsupported", "high", "Citation does not exist in retrieved evidence"
        elif citation_id in invalid_citations: status, risk, reason = "Unsupported", "high", "Citation failed scope, approval, publishability, or version validation"
        elif direct_conflict: status, risk, reason = "Contradicted", "high", "The cited evidence states the opposite of this claim"
        elif OVERSTATED_CERTAINTY.search(clean) and overlap < .75: status, risk, reason = "Not Verifiable", "high", "The claim presents unsupported certainty as fact"
        elif overlap >= .35: status, risk, reason = "Supported", "low", "Claim terms overlap with the cited approved evidence"
        elif overlap >= .15: status, risk, reason = "Partially Supported", "medium", "Only part of the claim is represented in cited evidence"
        else: status, risk, reason = "Unsupported", "high", "Cited evidence does not substantively match the claim"
        claims.append({"claim_text": claim, "citation_id": citation_id,
                       "evidence_excerpt": source.get("chunk_text", "")[:500] if source else None,
                       "validation_status": status, "risk_level": risk, "reason": reason,
                       "validator_version": VALIDATOR_VERSION})
    statuses = {item["validation_status"] for item in claims}
    if contradictions or "Contradicted" in statuses: overall = "Conflicting Evidence"
    elif any(item["risk_level"] == "critical" for item in claims): overall = "Human Investigation Required"
    elif "Unsupported" in statuses or not citation_validation.get("valid", False): overall = "Unsupported"
    elif "Partially Supported" in statuses or "Not Verifiable" in statuses: overall = "Partially Grounded"
    else: overall = "Grounded"
    return {"overall_status": overall, "claims": claims, "contradictions":contradictions,"validator_version": VALIDATOR_VERSION,
            "blocked": overall in {"Unsupported", "Conflicting Evidence", "Human Investigation Required"}}
