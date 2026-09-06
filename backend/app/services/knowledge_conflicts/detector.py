"""Real, executable knowledge-conflict detection.

Every function here reads already-persisted rows — approved knowledge
articles, real response-draft citations, real ResolutionConfirmation
outcomes, real Feedback edit ratios, real Ticket.reopened_count — and
never modifies an article. A conflict record is a review task, not an
automatic edit or deletion.
"""
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enterprise import ResolutionConfirmation
from app.models.feedback import Feedback
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.knowledge_conflict import KnowledgeConflict
from app.models.response_draft import ResponseDraft
from app.models.ticket import Ticket

# Identical method to ai/agents/grounding.py's contradiction check (shared
# term overlap + a positive/negative term pair), applied here across the
# whole approved knowledge corpus rather than one draft's cited evidence.
CONFLICT_PAIRS = (("enable", "disable"), ("required", "prohibited"), ("supported", "unsupported"))

MIN_RATE_SAMPLE = 3
LOW_SUCCESS_THRESHOLD = 0.5
HIGH_EDIT_RATIO_THRESHOLD = 0.5
HIGH_REOPEN_RATE_THRESHOLD = 0.3
UNUSED_MIN_AGE_DAYS = 90
MAX_ARTICLES_FOR_PAIRWISE_SCAN = 200
MAX_DRAFTS_SCANNED = 5000


def _dedup_key(article_a_id, article_b_id, conflict_type: str) -> str:
    ids = sorted([str(article_a_id), str(article_b_id or "")])
    return sha256(f"{conflict_type}:{ids[0]}:{ids[1]}".encode("utf-8")).hexdigest()[:64]


async def _get_or_flag(db: AsyncSession, tenant_id, article_a_id, article_b_id, conflict_type: str, severity: str, excerpt_a: str, excerpt_b: str | None, confidence: float | None, sample_size: int | None, affected_ticket_ids: list) -> KnowledgeConflict | None:
    key = _dedup_key(article_a_id, article_b_id, conflict_type)
    existing = await db.scalar(select(KnowledgeConflict).where(KnowledgeConflict.tenant_id == tenant_id, KnowledgeConflict.dedup_key == key))
    if existing:
        return None  # already flagged and tracked through its own review lifecycle; do not re-raise or overwrite an Admin's in-progress review
    conflict = KnowledgeConflict(
        tenant_id=tenant_id, article_a_id=article_a_id, article_b_id=article_b_id, dedup_key=key,
        conflict_type=conflict_type, severity=severity, evidence_excerpt_a=excerpt_a[:2000], evidence_excerpt_b=excerpt_b[:2000] if excerpt_b else None,
        confidence=confidence, sample_size=sample_size, affected_ticket_ids=[str(t) for t in affected_ticket_ids][:50], review_state="open",
    )
    db.add(conflict)
    await db.flush()
    return conflict


async def detect_contradictory_steps(db: AsyncSession, tenant_id) -> list[KnowledgeConflict]:
    articles = (await db.scalars(
        select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.tenant_id == tenant_id, KnowledgeBaseDocument.status == "approved", KnowledgeBaseDocument.is_publishable.is_(True))
        .limit(MAX_ARTICLES_FOR_PAIRWISE_SCAN)
    )).all()
    created = []
    for i in range(len(articles)):
        for j in range(i + 1, len(articles)):
            left, right = articles[i].content.lower(), articles[j].content.lower()
            shared = set(re.findall(r"[a-z0-9-]{5,}", left)) & set(re.findall(r"[a-z0-9-]{5,}", right))
            if len(shared) < 2:
                continue
            for positive, negative in CONFLICT_PAIRS:
                if (positive in left and negative in right) or (negative in left and positive in right):
                    # A heuristic proportional to shared-term overlap, clamped to [0,1] —
                    # NOT a calibrated probability. This lexical method (identical to
                    # ai/agents/grounding.py's per-draft check) is intentionally
                    # conservative but imprecise: on the real demo knowledge base it
                    # produces real false positives (e.g. two genuinely-unrelated
                    # troubleshooting articles that both happen to use "enable" and
                    # "disable" near shared networking vocabulary). It is a candidate
                    # for human review, never an automatic conclusion.
                    conflict = await _get_or_flag(
                        db, tenant_id, articles[i].id, articles[j].id, "contradictory_steps", "high",
                        articles[i].content[:500], articles[j].content[:500], confidence=min(1.0, len(shared) / 10), sample_size=None, affected_ticket_ids=[],
                    )
                    if conflict:
                        created.append(conflict)
                    break
    return created


async def _drafts_citing_article(db: AsyncSession, tenant_id, article_id) -> list[ResponseDraft]:
    drafts = (await db.scalars(select(ResponseDraft).where(ResponseDraft.tenant_id == tenant_id).order_by(ResponseDraft.created_at.desc()).limit(MAX_DRAFTS_SCANNED))).all()
    target = str(article_id)
    return [d for d in drafts if any(isinstance(c, dict) and c.get("article_id") == target for c in (d.citations or []))]


async def detect_rate_based_conflicts(db: AsyncSession, tenant_id) -> list[KnowledgeConflict]:
    articles = (await db.scalars(select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.tenant_id == tenant_id, KnowledgeBaseDocument.status == "approved"))).all()
    created = []
    for article in articles:
        citing_drafts = await _drafts_citing_article(db, tenant_id, article.id)
        if not citing_drafts:
            continue
        ticket_ids = list({d.ticket_id for d in citing_drafts})
        tickets = (await db.scalars(select(Ticket).where(Ticket.id.in_(ticket_ids)))).all()
        tickets_by_id = {t.id: t for t in tickets}

        confirmations = (await db.scalars(select(ResolutionConfirmation).where(ResolutionConfirmation.ticket_id.in_(ticket_ids)))).all()
        if len(confirmations) >= MIN_RATE_SAMPLE:
            solved = sum(1 for c in confirmations if c.outcome == "solved")
            rate = solved / len(confirmations)
            if rate < LOW_SUCCESS_THRESHOLD:
                conflict = await _get_or_flag(
                    db, tenant_id, article.id, None, "low_customer_success", "high" if rate < 0.25 else "medium",
                    f"Customer-confirmed success rate is {rate:.0%} across {len(confirmations)} confirmations for citations of this article.", None,
                    confidence=1 - rate, sample_size=len(confirmations), affected_ticket_ids=[c.ticket_id for c in confirmations],
                )
                if conflict:
                    created.append(conflict)

        feedback_rows = (await db.scalars(select(Feedback).where(Feedback.ticket_id.in_(ticket_ids), Feedback.action == "edit", Feedback.text_change_ratio.isnot(None)))).all()
        if len(feedback_rows) >= MIN_RATE_SAMPLE:
            avg_ratio = sum(float(f.text_change_ratio) for f in feedback_rows) / len(feedback_rows)
            if avg_ratio > HIGH_EDIT_RATIO_THRESHOLD:
                conflict = await _get_or_flag(
                    db, tenant_id, article.id, None, "high_engineer_edit_rate", "medium",
                    f"Engineers edited {avg_ratio:.0%} of the response text on average across {len(feedback_rows)} edited responses citing this article.", None,
                    confidence=avg_ratio, sample_size=len(feedback_rows), affected_ticket_ids=[f.ticket_id for f in feedback_rows],
                )
                if conflict:
                    created.append(conflict)

        if len(tickets) >= MIN_RATE_SAMPLE:
            reopened = sum(1 for t in tickets if t.reopened_count and t.reopened_count > 0)
            rate = reopened / len(tickets)
            if rate > HIGH_REOPEN_RATE_THRESHOLD:
                conflict = await _get_or_flag(
                    db, tenant_id, article.id, None, "high_reopen_rate", "high" if rate > 0.5 else "medium",
                    f"{reopened} of {len(tickets)} tickets citing this article were later reopened by the customer.", None,
                    confidence=rate, sample_size=len(tickets), affected_ticket_ids=[t.id for t in tickets if t.reopened_count and t.reopened_count > 0],
                )
                if conflict:
                    created.append(conflict)
    return created


async def detect_unused_articles(db: AsyncSession, tenant_id, min_age_days: int = UNUSED_MIN_AGE_DAYS) -> list[KnowledgeConflict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    articles = (await db.scalars(
        select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.tenant_id == tenant_id, KnowledgeBaseDocument.status == "approved", KnowledgeBaseDocument.created_at < cutoff)
    )).all()
    created = []
    for article in articles:
        citing_drafts = await _drafts_citing_article(db, tenant_id, article.id)
        if citing_drafts:
            continue
        conflict = await _get_or_flag(
            db, tenant_id, article.id, None, "unused_long_period", "low",
            f"No response draft has cited this article in the last {min_age_days}+ days since it was approved.", None,
            confidence=None, sample_size=0, affected_ticket_ids=[],
        )
        if conflict:
            created.append(conflict)
    return created


async def run_all_detectors(db: AsyncSession, tenant_id) -> list[KnowledgeConflict]:
    return (
        await detect_contradictory_steps(db, tenant_id)
        + await detect_rate_based_conflicts(db, tenant_id)
        + await detect_unused_articles(db, tenant_id)
    )


async def blocking_article_ids(db: AsyncSession, tenant_id, article_ids: list) -> set:
    """Article ids among the given set that currently have an open,
    high/critical-severity conflict — used by resolution_policy.py's
    no_unresolved_knowledge_conflict gate. Never returns an id based on a
    resolved or dismissed conflict; a human decision always clears the
    block."""
    if not article_ids:
        return set()
    from app.models.knowledge_conflict import BLOCKING_SEVERITIES
    rows = (await db.scalars(
        select(KnowledgeConflict).where(
            KnowledgeConflict.tenant_id == tenant_id, KnowledgeConflict.review_state == "open",
            KnowledgeConflict.severity.in_(BLOCKING_SEVERITIES),
        )
    )).all()
    article_id_strs = {str(a) for a in article_ids}
    blocked = set()
    for row in rows:
        if str(row.article_a_id) in article_id_strs:
            blocked.add(str(row.article_a_id))
        if row.article_b_id and str(row.article_b_id) in article_id_strs:
            blocked.add(str(row.article_b_id))
    return blocked
