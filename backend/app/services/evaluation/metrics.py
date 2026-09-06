"""Exact classification metrics for the Evaluation Lab.

Every number here comes from scikit-learn's metric implementations run
against real predictions and real labels — nothing is estimated, sampled
from a template, or hard-coded. Callers are responsible for only passing
rows that actually have a ground-truth label; this module never guesses at
missing labels.
"""


def classification_report_exact(
    y_true: list[str],
    y_pred: list[str],
    labels: list[str],
    y_proba: list[list[float]] | None = None,
    proba_classes: list[str] | None = None,
    top_k_values: tuple[int, ...] = (2, 3),
) -> dict:
    from sklearn.metrics import (
        accuracy_score, confusion_matrix, precision_recall_fscore_support, top_k_accuracy_score,
    )

    if not y_true:
        raise ValueError("classification_report_exact requires at least one labelled example")

    accuracy = float(accuracy_score(y_true, y_pred))
    overall: dict[str, dict[str, float]] = {}
    for average in ("macro", "micro", "weighted"):
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, y_pred, labels=labels, average=average, zero_division=0
        )
        overall[average] = {"precision": float(precision), "recall": float(recall), "f1": float(f1)}

    per_class_p, per_class_r, per_class_f, per_class_support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average=None, zero_division=0
    )
    per_class = {
        label: {
            "precision": float(per_class_p[i]),
            "recall": float(per_class_r[i]),
            "f1": float(per_class_f[i]),
            "support": int(per_class_support[i]),
        }
        for i, label in enumerate(labels)
    }

    matrix = confusion_matrix(y_true, y_pred, labels=labels).tolist()

    top_k_accuracy: dict[str, float | None] = {}
    if y_proba is not None and proba_classes is not None:
        for k in top_k_values:
            if k >= len(proba_classes):
                top_k_accuracy[f"top_{k}_accuracy"] = None
                continue
            try:
                top_k_accuracy[f"top_{k}_accuracy"] = float(
                    top_k_accuracy_score(y_true, y_proba, k=k, labels=proba_classes)
                )
            except ValueError:
                top_k_accuracy[f"top_{k}_accuracy"] = None

    return {
        "accuracy": accuracy,
        "overall": overall,
        "per_class": per_class,
        "confusion_matrix": {"labels": labels, "matrix": matrix},
        "top_k_accuracy": top_k_accuracy,
    }
