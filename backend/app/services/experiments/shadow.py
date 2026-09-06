"""Shadow-mode sampling and champion/challenger comparison for the
department/priority/sentiment classifiers.

A shadow run reads a ticket's already-stored text, runs it through the
champion and challenger artifacts, and writes one row to ``shadow_runs``.
It never sets, updates, or reads any field on ``Ticket`` other than the
text needed to classify, never changes assignment/routing/status, and never
returns the challenger's output anywhere a customer or the live pipeline
could see it — it is purely an offline, Admin-visible comparison.
"""
import asyncio
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.experiment import ShadowRun
from app.models.ticket import Ticket
from app.models.v2_governance import ProviderModel
from app.services.evaluation.threshold_simulation import wilson_interval
from app.services.ticket_intelligence import redact

ARTIFACTS_DIR = Path(__file__).resolve().parents[4] / "ai" / "models" / "artifacts"
MAX_SAMPLE_SIZE = 200
MIN_COMPARISON_SAMPLE = 20

_artifact_cache: dict[str, object] = {}


class ArtifactUnavailable(RuntimeError):
    pass


def _resolve_artifact_path(config_reference: str) -> Path:
    if not config_reference.startswith("file:"):
        raise ArtifactUnavailable(f"config_reference '{config_reference}' does not name a local artifact file")
    relative = config_reference[len("file:"):]
    path = (ARTIFACTS_DIR / relative).resolve()
    if ARTIFACTS_DIR not in path.parents and path != ARTIFACTS_DIR:
        raise ArtifactUnavailable("config_reference must resolve inside the trusted artifacts directory")
    if not path.exists():
        raise ArtifactUnavailable(f"Artifact file not found: {path}")
    return path


def _load(config_reference: str):
    if config_reference in _artifact_cache:
        return _artifact_cache[config_reference]
    import joblib
    path = _resolve_artifact_path(config_reference)
    model = joblib.load(path)
    _artifact_cache[config_reference] = model
    return model


async def _predict(config_reference: str, text: str) -> tuple[str | None, float | None, int]:
    started = time.perf_counter()
    try:
        model = await asyncio.to_thread(_load, config_reference)
        label = str((await asyncio.to_thread(model.predict, [text]))[0])
        confidence = None
        if hasattr(model, "predict_proba"):
            probabilities = (await asyncio.to_thread(model.predict_proba, [text]))[0]
            confidence = float(max(probabilities))
        latency_ms = int((time.perf_counter() - started) * 1000)
        return label, confidence, latency_ms
    except ArtifactUnavailable:
        return None, None, int((time.perf_counter() - started) * 1000)


async def run_shadow_sample(db: AsyncSession, tenant_id, task_type: str, sample_size: int, created_by) -> dict:
    sample_size = min(sample_size, MAX_SAMPLE_SIZE)
    champion = await db.scalar(select(ProviderModel).where(
        ProviderModel.tenant_id == tenant_id, ProviderModel.task_type == task_type,
        ProviderModel.lifecycle_role == "champion", ProviderModel.enabled.is_(True),
    ))
    challenger = await db.scalar(select(ProviderModel).where(
        ProviderModel.tenant_id == tenant_id, ProviderModel.task_type == task_type, ProviderModel.lifecycle_role == "challenger",
    ).order_by(ProviderModel.created_at.desc()))

    if not champion or not challenger:
        missing = [name for name, row in (("champion", champion), ("challenger", challenger)) if not row]
        return {"status": "not_configured", "sample_size": 0, "missing": missing, "reason": f"No {' or '.join(missing)} model is registered for task '{task_type}' yet."}
    if not champion.config_reference or not challenger.config_reference:
        return {"status": "not_configured", "sample_size": 0, "missing": [], "reason": "Champion or challenger has no config_reference to load an artifact from."}

    label_field = {"department": None, "priority": "priority", "sentiment": "sentiment"}[task_type]
    already_sampled = select(ShadowRun.ticket_id).where(ShadowRun.tenant_id == tenant_id, ShadowRun.task_type == task_type, ShadowRun.challenger_model_id == challenger.id)
    query = select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.deleted_at.is_(None), Ticket.id.notin_(already_sampled))
    if task_type == "department":
        query = query.where(Ticket.department_id.isnot(None))
    else:
        query = query.where(getattr(Ticket, label_field).isnot(None))
    tickets = (await db.scalars(query.order_by(Ticket.updated_at.desc()).limit(sample_size))).all()

    if not tickets:
        return {"status": "no_unsampled_tickets", "sample_size": 0, "missing": [], "reason": "Every eligible ticket has already been sampled against this challenger."}

    from app.models.department import Department
    created = 0
    for ticket in tickets:
        text, _ = redact(f"{ticket.subject}\n{ticket.description}")
        actual_label = None
        if task_type == "department" and ticket.department_id:
            department = await db.get(Department, ticket.department_id)
            actual_label = department.name if department else None
        elif label_field:
            actual_label = getattr(ticket, label_field)

        champion_label, champion_conf, champion_ms = await _predict(champion.config_reference, text)
        challenger_label, challenger_conf, challenger_ms = await _predict(challenger.config_reference, text)
        db.add(ShadowRun(
            tenant_id=tenant_id, ticket_id=ticket.id, task_type=task_type,
            champion_model_id=champion.id, challenger_model_id=challenger.id,
            redacted_input=text[:2000], input_hash=sha256(text.encode("utf-8")).hexdigest(),
            actual_label=actual_label, champion_output=champion_label, champion_confidence=champion_conf,
            champion_latency_ms=champion_ms, challenger_output=challenger_label, challenger_confidence=challenger_conf,
            challenger_latency_ms=challenger_ms,
            agreement=(champion_label == challenger_label) if champion_label and challenger_label else None,
            created_by=created_by,
        ))
        created += 1

    return {"status": "sampled", "sample_size": created, "missing": [], "reason": None, "champion_model_id": champion.id, "challenger_model_id": challenger.id}


async def compare_champion_challenger(db: AsyncSession, tenant_id, task_type: str) -> dict:
    rows = (await db.scalars(select(ShadowRun).where(ShadowRun.tenant_id == tenant_id, ShadowRun.task_type == task_type).order_by(ShadowRun.created_at.desc()))).all()
    sample_size = len(rows)
    if sample_size == 0:
        return {"sample_size": 0, "data_sufficient": False, "reason": "No shadow runs have been recorded for this task yet.", "agreement_rate": None, "champion_accuracy": None, "challenger_accuracy": None, "challenger_accuracy_ci": None, "avg_champion_latency_ms": None, "avg_challenger_latency_ms": None}

    agreements = [r for r in rows if r.agreement is not None]
    agreement_rate = sum(1 for r in agreements if r.agreement) / len(agreements) if agreements else None

    labeled = [r for r in rows if r.actual_label]
    champion_correct = sum(1 for r in labeled if r.champion_output == r.actual_label)
    challenger_correct = sum(1 for r in labeled if r.challenger_output == r.actual_label)
    champion_accuracy = champion_correct / len(labeled) if labeled else None
    challenger_accuracy = challenger_correct / len(labeled) if labeled else None
    challenger_ci = wilson_interval(challenger_correct, len(labeled)) if labeled else None

    champion_latencies = [r.champion_latency_ms for r in rows if r.champion_latency_ms is not None]
    challenger_latencies = [r.challenger_latency_ms for r in rows if r.challenger_latency_ms is not None]

    return {
        "sample_size": sample_size, "data_sufficient": len(labeled) >= MIN_COMPARISON_SAMPLE,
        "reason": None if len(labeled) >= MIN_COMPARISON_SAMPLE else f"Only {len(labeled)} labelled comparisons recorded (minimum {MIN_COMPARISON_SAMPLE}).",
        "agreement_rate": round(agreement_rate, 4) if agreement_rate is not None else None,
        "champion_accuracy": round(champion_accuracy, 4) if champion_accuracy is not None else None,
        "challenger_accuracy": round(challenger_accuracy, 4) if challenger_accuracy is not None else None,
        "challenger_accuracy_ci": [round(challenger_ci[0], 4), round(challenger_ci[1], 4)] if challenger_ci else None,
        "avg_champion_latency_ms": round(sum(champion_latencies) / len(champion_latencies), 1) if champion_latencies else None,
        "avg_challenger_latency_ms": round(sum(challenger_latencies) / len(challenger_latencies), 1) if challenger_latencies else None,
    }


CHAMPION_HEALTH_MIN_ACCURACY = 0.5


async def check_champion_health_and_rollback(db: AsyncSession, tenant_id, task_type: str, actor_id) -> dict:
    """Reads the champion's own recent shadow-comparison accuracy (the
    champion's predictions vs. real ticket labels — not the challenger's)
    and, only if it has fallen below a fixed floor AND a known-good rollback
    target exists, executes the exact same promote/rollback transition
    app.routers.v2_governance already uses for a manual rollback. This never
    promotes a challenger automatically — only ever retreats to a
    previously-active, already-approved champion."""
    from app.models.v2_governance import ModelDeployment

    champion = await db.scalar(select(ProviderModel).where(
        ProviderModel.tenant_id == tenant_id, ProviderModel.task_type == task_type,
        ProviderModel.lifecycle_role == "champion", ProviderModel.enabled.is_(True),
    ).with_for_update())
    if not champion:
        return {"action": "none", "reason": "No active champion is registered for this task."}

    labeled_runs = (await db.scalars(select(ShadowRun).where(
        ShadowRun.tenant_id == tenant_id, ShadowRun.task_type == task_type,
        ShadowRun.champion_model_id == champion.id, ShadowRun.actual_label.isnot(None),
    ))).all()
    if len(labeled_runs) < MIN_COMPARISON_SAMPLE:
        return {"action": "none", "reason": f"Only {len(labeled_runs)} labelled champion observations recorded (minimum {MIN_COMPARISON_SAMPLE} required before a health judgement is made).", "sample_size": len(labeled_runs)}

    correct = sum(1 for r in labeled_runs if r.champion_output == r.actual_label)
    accuracy = correct / len(labeled_runs)
    if accuracy >= CHAMPION_HEALTH_MIN_ACCURACY:
        return {"action": "none", "reason": "Champion accuracy is within the healthy range.", "accuracy": round(accuracy, 4), "sample_size": len(labeled_runs)}
    if not champion.rollback_target_id:
        return {"action": "none", "reason": "Champion accuracy is unhealthy but no rollback target is recorded — human intervention required.", "accuracy": round(accuracy, 4), "sample_size": len(labeled_runs)}

    target = await db.scalar(select(ProviderModel).where(ProviderModel.id == champion.rollback_target_id, ProviderModel.tenant_id == tenant_id).with_for_update())
    if not target:
        return {"action": "none", "reason": "Rollback target is no longer available — human intervention required.", "accuracy": round(accuracy, 4), "sample_size": len(labeled_runs)}

    # Retiring the old champion must be flushed to the database before the
    # new champion is activated — the partial unique index on (tenant_id,
    # task_type, deployment_environment) WHERE lifecycle_role='champion' AND
    # enabled=true is checked per-statement, and SQLAlchemy does not
    # guarantee it will emit these two UPDATEs in attribute-assignment
    # order. Without this intermediate flush, the second UPDATE can run
    # first and spuriously violate the constraint against the still-active
    # old champion row.
    champion.lifecycle_role = "retired"
    champion.enabled = False
    await db.flush()
    target.lifecycle_role = "champion"
    target.enabled = True
    target.deployed_by = actor_id
    target.deployed_at = datetime.now(timezone.utc)
    db.add(ModelDeployment(
        tenant_id=tenant_id, task_type=task_type, from_model_id=champion.id, to_model_id=target.id, action="rollback",
        actor_id=actor_id, reason=f"Automatic health-triggered rollback: champion accuracy {accuracy:.1%} fell below the {CHAMPION_HEALTH_MIN_ACCURACY:.0%} floor over {len(labeled_runs)} labelled observations.",
        evaluation_snapshot={"accuracy": accuracy, "sample_size": len(labeled_runs), "trigger": "automatic_health_check"},
    ))
    await db.flush()
    return {"action": "rolled_back", "reason": f"Champion accuracy {accuracy:.1%} fell below the {CHAMPION_HEALTH_MIN_ACCURACY:.0%} floor; rolled back to the prior champion.", "accuracy": round(accuracy, 4), "sample_size": len(labeled_runs), "from_model_id": champion.id, "to_model_id": target.id}
