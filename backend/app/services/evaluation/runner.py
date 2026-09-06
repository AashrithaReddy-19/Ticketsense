"""Orchestrates a single reproducible evaluation run: loads the requested
dataset version's test split, runs the existing deterministic classifier
artifact against it, computes exact metrics, and persists everything needed
to reproduce or audit the result later.

A run never trains anything and never mutates the classifier — it is a
read-only measurement against a frozen artifact and a frozen dataset
version. Rows without a usable ground-truth label are excluded and counted,
never silently coerced into a label they weren't given.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetRow, DatasetVersion
from app.models.evaluation import EvaluationArtifact, EvaluationExample, EvaluationMetric, EvaluationRun
from app.services.evaluation import classifier_eval, metrics

MIN_EVALUATION_ROWS = 5
LABEL_FIELD = {"department": "label_department", "priority": "label_priority", "sentiment": "label_sentiment"}


class EvaluationRunError(ValueError):
    pass


async def run_classification_evaluation(db: AsyncSession, tenant_id, dataset_version_id, target: str, user_id, notes: str | None = None) -> EvaluationRun:
    if target not in LABEL_FIELD:
        raise EvaluationRunError(f"Unknown evaluation target: {target}")

    version = await db.scalar(select(DatasetVersion).where(DatasetVersion.id == dataset_version_id))
    if not version:
        raise EvaluationRunError("Dataset version not found")
    if version.status != "ready":
        raise EvaluationRunError(f"Dataset version status is '{version.status}', not 'ready'")

    started_at = datetime.now(timezone.utc)
    label_field = LABEL_FIELD[target]
    rows = (await db.scalars(
        select(DatasetRow).where(DatasetRow.dataset_version_id == dataset_version_id, DatasetRow.split == "test")
    )).all()

    exclusion_reasons: dict[str, int] = {}
    considered_rows: list[DatasetRow] = []
    for row in rows:
        label = getattr(row, label_field)
        if not label:
            exclusion_reasons["missing_label"] = exclusion_reasons.get("missing_label", 0) + 1
            continue
        considered_rows.append(row)

    try:
        classifier = await classifier_eval.get_classifier(target)
    except classifier_eval.ClassifierArtifactUnavailable as exc:
        run = EvaluationRun(
            tenant_id=tenant_id, dataset_version_id=dataset_version_id, target=target,
            model_artifact_path=str(classifier_eval.artifact_path(target)), status="insufficient_data",
            row_count_considered=0, row_count_excluded=len(rows), exclusion_reasons={"artifact_unavailable": str(exc)},
            started_at=started_at, completed_at=datetime.now(timezone.utc), notes=notes, created_by=user_id,
        )
        db.add(run)
        await db.flush()
        return run

    known_classes = {str(c) for c in classifier.classes_}
    label_mismatch = [row for row in considered_rows if getattr(row, label_field) not in known_classes]
    if label_mismatch:
        exclusion_reasons["label_not_in_model_classes"] = len(label_mismatch)
        considered_rows = [row for row in considered_rows if row not in label_mismatch]

    if len(considered_rows) < MIN_EVALUATION_ROWS:
        run = EvaluationRun(
            tenant_id=tenant_id, dataset_version_id=dataset_version_id, target=target,
            model_artifact_path=str(classifier_eval.artifact_path(target)),
            model_artifact_hash=classifier_eval.artifact_content_hash(target),
            environment_info=classifier_eval.environment_info(), git_commit=classifier_eval.git_commit(),
            status="insufficient_data", row_count_considered=len(considered_rows), row_count_excluded=len(rows) - len(considered_rows),
            exclusion_reasons={**exclusion_reasons, "reason": f"Fewer than {MIN_EVALUATION_ROWS} labelled test rows available"},
            started_at=started_at, completed_at=datetime.now(timezone.utc), notes=notes, created_by=user_id,
        )
        db.add(run)
        await db.flush()
        return run

    texts = [row.redacted_text for row in considered_rows]
    true_labels = [getattr(row, label_field) for row in considered_rows]
    predicted_labels, probabilities, proba_classes = await classifier_eval.predict(target, texts)

    label_space = sorted(set(true_labels) | set(predicted_labels))
    report = metrics.classification_report_exact(
        true_labels, predicted_labels, label_space, y_proba=probabilities, proba_classes=proba_classes,
    )

    run = EvaluationRun(
        tenant_id=tenant_id, dataset_version_id=dataset_version_id, target=target,
        model_artifact_path=str(classifier_eval.artifact_path(target)),
        model_artifact_hash=classifier_eval.artifact_content_hash(target),
        git_commit=classifier_eval.git_commit(), environment_info=classifier_eval.environment_info(),
        config_snapshot={"pipeline_steps": [step for step, _ in classifier.steps]} if hasattr(classifier, "steps") else {},
        split_used="test", status="completed", row_count_considered=len(considered_rows),
        row_count_excluded=len(rows) - len(considered_rows), exclusion_reasons=exclusion_reasons,
        started_at=started_at, completed_at=datetime.now(timezone.utc), notes=notes, created_by=user_id,
    )
    db.add(run)
    await db.flush()

    for row, true_label, predicted_label, proba_row in zip(
        considered_rows, true_labels, predicted_labels, probabilities or [None] * len(considered_rows)
    ):
        top_3_hit = None
        confidence = None
        if proba_row is not None and proba_classes is not None:
            ranked = sorted(zip(proba_classes, proba_row), key=lambda pair: pair[1], reverse=True)
            top_3_hit = true_label in [label for label, _ in ranked[:3]]
            confidence = max(proba_row)
        db.add(EvaluationExample(
            run_id=run.id, dataset_row_id=row.id, true_label=true_label, predicted_label=predicted_label,
            correct=(true_label == predicted_label), top_3_hit=top_3_hit, predicted_confidence=confidence,
        ))

    db.add(EvaluationMetric(run_id=run.id, scope="overall", metric_name="accuracy", metric_value=report["accuracy"]))
    for average, values in report["overall"].items():
        for metric_name, value in values.items():
            db.add(EvaluationMetric(run_id=run.id, scope="overall", metric_name=f"{average}_{metric_name}", metric_value=value))
    for metric_name, value in report["top_k_accuracy"].items():
        if value is not None:
            db.add(EvaluationMetric(run_id=run.id, scope="overall", metric_name=metric_name, metric_value=value))
    for class_label, values in report["per_class"].items():
        for metric_name in ("precision", "recall", "f1"):
            db.add(EvaluationMetric(run_id=run.id, scope="per_class", class_label=class_label, metric_name=metric_name, metric_value=values[metric_name], support=values["support"]))

    db.add(EvaluationArtifact(run_id=run.id, artifact_type="confusion_matrix", content=report["confusion_matrix"]))
    return run
