"""Dataset ingestion: parsing, schema validation, redaction, deduplication,
language heuristics and leakage-safe train/validation/test splitting.

Every technique here is deterministic and documented as such — there is no
trained model in this module. Near-duplicate detection uses lexical n-gram
overlap, not semantic embeddings, and is explicitly labelled as a lexical
heuristic rather than an ML result, per the project rule against describing
deterministic rules as trained predictions.
"""
import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from hashlib import sha256

from app.services.ticket_intelligence import redact as base_redact

PRIORITY_VALUES = {"low", "medium", "high", "urgent"}
SENTIMENT_VALUES = {"positive", "neutral", "negative"}

EXTRA_PII_PATTERNS = {
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}

# A tiny, fixed function-word list is enough to distinguish English from
# non-English text for a demo-scale corpus without adding a language-ID
# model dependency. This is a lightweight heuristic, not a trained
# classifier — datasets in other languages are labelled "unknown" rather
# than guessed at.
_ENGLISH_STOPWORDS = {"the", "is", "and", "to", "of", "a", "in", "for", "on", "my", "i", "it", "not", "was"}

MAX_PAIRWISE_ROWS = 2000
NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.9


class DatasetValidationError(ValueError):
    """Raised when a dataset file cannot be parsed or has no schema-valid rows at all."""


@dataclass
class ParsedRow:
    row_index: int
    raw: dict
    errors: list[str] = field(default_factory=list)


@dataclass
class ProcessedRow:
    row_index: int
    group_key: str
    redacted_text: str
    content_hash: str
    language_code: str
    pii_categories: list[str]
    corruption_flags: list[str]
    label_department: str | None = None
    label_priority: str | None = None
    label_sentiment: str | None = None
    query_text: str | None = None
    relevant_document_ref: str | None = None
    relevance_grade: int | None = None
    near_duplicate_of: int | None = None  # row_index of the earlier duplicate, if any
    split: str | None = None


def parse_records(raw_bytes: bytes, source_format: str) -> list[dict]:
    """Parse CSV/JSON/JSONL bytes into a list of dict records with normalized encoding."""
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_bytes.decode("utf-8", errors="replace")
    text = unicodedata.normalize("NFC", text)
    if source_format == "csv":
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]
    if source_format == "jsonl":
        records = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
        return records
    if source_format == "json":
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("records") or payload.get("rows") or [payload]
        if not isinstance(payload, list):
            raise DatasetValidationError("JSON dataset must be a list of records or a {records: [...]} object")
        return payload
    raise DatasetValidationError(f"Unsupported source format: {source_format}")


def _extended_redact(text: str) -> tuple[str, list[str]]:
    # Credit-card and SSN patterns must run BEFORE the shared email/phone/secret
    # pass: the shared "phone" pattern is a greedy 9-14-digit run and will
    # otherwise consume credit-card and SSN digit sequences first, silently
    # mislabeling them as "phone" and leaving these categories unreachable.
    clean = text
    categories: list[str] = []
    for label, pattern in EXTRA_PII_PATTERNS.items():
        if pattern.search(clean):
            categories.append(label)
            clean = pattern.sub(f"[{label.upper()} REDACTED]", clean)
    clean, base_categories = base_redact(clean)
    categories.extend(base_categories)
    return clean, categories


def _detect_language(text: str) -> str:
    tokens = re.findall(r"[a-zA-Z']+", text.lower())
    if not tokens:
        return "unknown"
    hits = sum(1 for token in tokens if token in _ENGLISH_STOPWORDS)
    return "en" if hits / max(len(tokens), 1) >= 0.03 else "unknown"


def _normalize_for_hash(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _content_hash(text: str) -> str:
    return sha256(_normalize_for_hash(text).encode("utf-8")).hexdigest()


def _shingles(text: str, n: int = 3) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def validate_and_process(records: list[dict], kind: str) -> tuple[list[ProcessedRow], dict[int, list[str]]]:
    """Validate schema, redact PII, flag corruption and compute per-row content hashes.

    Returns (processed_rows, rejected_rows_with_reasons). Rejected rows are
    dropped entirely — their raw content (which may contain PII) is never
    persisted, only the row index and a redaction-safe rejection reason.
    """
    processed: list[ProcessedRow] = []
    rejected: dict[int, list[str]] = {}
    for index, raw in enumerate(records):
        errors: list[str] = []
        if not isinstance(raw, dict):
            rejected[index] = ["Row is not a JSON object"]
            continue
        if kind == "ticket_labels":
            text = str(raw.get("text") or "").strip()
            if not text:
                subject = str(raw.get("subject") or "").strip()
                description = str(raw.get("description") or "").strip()
                text = f"{subject} {description}".strip()
            if not text:
                errors.append("Missing required text (either 'text', or 'subject'+'description')")
            priority = (raw.get("priority") or None)
            if priority and str(priority).lower() not in PRIORITY_VALUES:
                errors.append(f"Unknown priority label: {priority!r}")
            sentiment = (raw.get("sentiment") or None)
            if sentiment and str(sentiment).lower() not in SENTIMENT_VALUES:
                errors.append(f"Unknown sentiment label: {sentiment!r}")
        elif kind == "retrieval_judgments":
            text = str(raw.get("query") or "").strip()
            if not text:
                errors.append("Missing required 'query'")
            if not str(raw.get("document_ref") or "").strip():
                errors.append("Missing required 'document_ref'")
            grade = raw.get("relevance_grade")
            try:
                grade_int = int(grade)
                if not (0 <= grade_int <= 3):
                    errors.append("relevance_grade must be between 0 and 3")
            except (TypeError, ValueError):
                errors.append(f"relevance_grade must be an integer, got {grade!r}")
        else:
            raise DatasetValidationError(f"Unknown dataset kind: {kind}")
        if errors:
            rejected[index] = errors
            continue

        corruption_flags = []
        if len(text) < 3:
            corruption_flags.append("text_too_short")
        control_chars = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\t")
        if control_chars > 0:
            corruption_flags.append("control_characters_stripped")
            text = "".join(ch for ch in text if not (ord(ch) < 32 and ch not in "\n\t"))

        redacted_text, pii_categories = _extended_redact(text)
        group_key = str(raw.get("group_key") or raw.get("thread_id") or raw.get("ticket_id") or f"row-{index}")

        row = ProcessedRow(
            row_index=index,
            group_key=group_key,
            redacted_text=redacted_text,
            content_hash=_content_hash(redacted_text),
            language_code=_detect_language(redacted_text),
            pii_categories=sorted(set(pii_categories)),
            corruption_flags=corruption_flags,
        )
        if kind == "ticket_labels":
            row.label_department = raw.get("department") or None
            row.label_priority = str(raw.get("priority")).lower() if raw.get("priority") else None
            row.label_sentiment = str(raw.get("sentiment")).lower() if raw.get("sentiment") else None
        else:
            row.query_text = redacted_text
            row.relevant_document_ref = str(raw.get("document_ref"))
            row.relevance_grade = int(raw.get("relevance_grade"))
        processed.append(row)

    _flag_exact_duplicates(processed)
    return processed, rejected


def _flag_exact_duplicates(rows: list[ProcessedRow]) -> None:
    seen: dict[str, int] = {}
    for row in rows:
        if row.content_hash in seen:
            row.corruption_flags.append("exact_duplicate")
            row.near_duplicate_of = seen[row.content_hash]
        else:
            seen[row.content_hash] = row.row_index


def detect_cross_split_near_duplicates(rows: list[ProcessedRow]) -> tuple[int, bool]:
    """Flag lexical near-duplicates (Jaccard >= 0.9 on word 3-grams) that ended
    up in different splits — the actual leakage risk. Same-group rows always
    share a split by construction, so this only ever fires across groups.
    Skipped (and honestly reported as skipped) above MAX_PAIRWISE_ROWS since
    the check is O(n^2) and this is a lexical heuristic, not an indexed
    similarity search.
    """
    if len(rows) > MAX_PAIRWISE_ROWS:
        return 0, True
    shingles = [_shingles(row.redacted_text) for row in rows]
    leaked = 0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if rows[i].split == rows[j].split:
                continue
            if _jaccard(shingles[i], shingles[j]) >= NEAR_DUPLICATE_JACCARD_THRESHOLD:
                leaked += 1
                rows[j].corruption_flags.append(f"near_duplicate_cross_split_of_row_{rows[i].row_index}")
    return leaked, False


def assign_leakage_safe_splits(rows: list[ProcessedRow], ratios: tuple[float, float, float], seed: str) -> None:
    """Assign every row a split, keeping every row that shares a group_key in
    the same split (thread/entity-grouped, not row-level) — this is what
    prevents the same ticket thread or query topic from leaking across
    train/validation/test. Group order is a stable SHA-256 hash of
    (seed, group_key), so the assignment is reproducible for a given dataset
    version and independent of input row order. Groups are then assigned
    greedily to whichever split has the largest remaining share of its
    target count — a deterministic bin-packing heuristic, not a statistical
    guarantee of exact ratios when group sizes are uneven.
    """
    groups: dict[str, list[ProcessedRow]] = {}
    for row in rows:
        groups.setdefault(row.group_key, []).append(row)
    total = len(rows)
    targets = {"train": total * ratios[0], "validation": total * ratios[1], "test": total * ratios[2]}
    assigned = {"train": 0, "validation": 0, "test": 0}
    ordered_groups = sorted(groups, key=lambda key: sha256(f"{seed}:{key}".encode("utf-8")).hexdigest())
    for group_key in ordered_groups:
        members = groups[group_key]
        split = max(("train", "validation", "test"), key=lambda s: targets[s] - assigned[s])
        for row in members:
            row.split = split
        assigned[split] += len(members)


def build_quality_report(rows: list[ProcessedRow], rejected: dict[int, list[str]], near_dup_count: int, near_dup_skipped: bool) -> dict:
    total_seen = len(rows) + len(rejected)
    label_distribution: dict[str, dict[str, int]] = {"department": {}, "priority": {}, "sentiment": {}, "relevance_grade": {}}
    missing = {"label_department": 0, "label_priority": 0, "label_sentiment": 0}
    duplicates = 0
    corrupted = 0
    for row in rows:
        if "exact_duplicate" in row.corruption_flags:
            duplicates += 1
        if row.corruption_flags:
            corrupted += 1
        if row.label_department:
            label_distribution["department"][row.label_department] = label_distribution["department"].get(row.label_department, 0) + 1
        else:
            missing["label_department"] += 1
        if row.label_priority:
            label_distribution["priority"][row.label_priority] = label_distribution["priority"].get(row.label_priority, 0) + 1
        else:
            missing["label_priority"] += 1
        if row.label_sentiment:
            label_distribution["sentiment"][row.label_sentiment] = label_distribution["sentiment"].get(row.label_sentiment, 0) + 1
        else:
            missing["label_sentiment"] += 1
        if row.relevance_grade is not None:
            key = str(row.relevance_grade)
            label_distribution["relevance_grade"][key] = label_distribution["relevance_grade"].get(key, 0) + 1
    accepted = len(rows)
    return {
        "raw_row_count": total_seen,
        "accepted_row_count": accepted,
        "rejected_row_count": len(rejected),
        "rejection_reasons": {str(index): reasons for index, reasons in rejected.items()},
        "duplicate_rate": round(duplicates / accepted, 4) if accepted else 0.0,
        "corruption_rate": round(corrupted / accepted, 4) if accepted else 0.0,
        "near_duplicate_cross_split_count": near_dup_count,
        "near_duplicate_check_skipped": near_dup_skipped,
        "label_distribution": label_distribution,
        "missing_data_stats": missing,
        "language_summary": _language_summary(rows),
        "split_counts": _split_counts(rows),
    }


def _language_summary(rows: list[ProcessedRow]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        summary[row.language_code] = summary.get(row.language_code, 0) + 1
    return summary


def _split_counts(rows: list[ProcessedRow]) -> dict[str, int]:
    summary: dict[str, int] = {"train": 0, "validation": 0, "test": 0}
    for row in rows:
        if row.split:
            summary[row.split] += 1
    return summary


def dataset_version_content_hash(rows: list[ProcessedRow]) -> str:
    """A version-level hash of all accepted rows' content, independent of row
    order, so re-uploading the same data (in any order) yields the same
    dataset version identity, and any content change is detectable."""
    digest = sha256()
    for content_hash in sorted(row.content_hash for row in rows):
        digest.update(content_hash.encode("utf-8"))
    return digest.hexdigest()
