import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.evaluation.ingestion import (
    ProcessedRow,
    assign_leakage_safe_splits,
    dataset_version_content_hash,
    detect_cross_split_near_duplicates,
    parse_records,
    validate_and_process,
)


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_parse_records_supports_csv_json_and_jsonl():
    csv_bytes = b"text,department\nVPN is down,Networking\n"
    assert parse_records(csv_bytes, "csv") == [{"text": "VPN is down", "department": "Networking"}]

    json_bytes = b'{"records": [{"text": "a"}, {"text": "b"}]}'
    assert parse_records(json_bytes, "json") == [{"text": "a"}, {"text": "b"}]

    jsonl_bytes = b'{"text": "a"}\n{"text": "b"}\n'
    assert parse_records(jsonl_bytes, "jsonl") == [{"text": "a"}, {"text": "b"}]


def test_schema_validation_rejects_missing_fields_and_unknown_labels():
    records = [
        {"text": "VPN issue", "priority": "high"},
        {"text": ""},
        {"priority": "not-a-real-priority", "text": "still has text"},
    ]
    processed, rejected = validate_and_process(records, "ticket_labels")
    assert len(processed) == 1
    assert 1 in rejected and "Missing required text" in rejected[1][0]
    assert 2 in rejected and "Unknown priority label" in rejected[2][0]


def test_retrieval_judgments_require_query_document_and_grade_in_range():
    records = [
        {"query": "how to reset vpn", "document_ref": "kb-1", "relevance_grade": 2},
        {"query": "missing doc ref", "relevance_grade": 1},
        {"query": "bad grade", "document_ref": "kb-2", "relevance_grade": 9},
    ]
    processed, rejected = validate_and_process(records, "retrieval_judgments")
    assert len(processed) == 1
    assert processed[0].relevance_grade == 2
    assert "Missing required 'document_ref'" in rejected[1][0]
    assert "relevance_grade must be between 0 and 3" in rejected[2][0]


def test_pii_and_secret_redaction_covers_extended_categories():
    text = "Contact me at person@example.com, card 4111 1111 1111 1111, ssn 123-45-6789, api_key=abcdef"
    processed, rejected = validate_and_process([{"text": text}], "ticket_labels")
    assert not rejected
    categories = set(processed[0].pii_categories)
    assert {"email", "credit_card", "ssn", "secret"} <= categories
    assert "example.com" not in processed[0].redacted_text
    assert "4111" not in processed[0].redacted_text
    assert "123-45-6789" not in processed[0].redacted_text


def test_exact_duplicate_rows_are_flagged_and_linked():
    records = [{"text": "The VPN client fails to connect."}, {"text": "the vpn client fails to connect."}]
    processed, rejected = validate_and_process(records, "ticket_labels")
    assert not rejected
    assert "exact_duplicate" not in processed[0].corruption_flags
    assert "exact_duplicate" in processed[1].corruption_flags
    assert processed[1].near_duplicate_of == 0


def test_leakage_safe_split_keeps_every_group_together():
    records = []
    for i in range(12):
        group = f"thread-{i // 3}"
        records.append({"text": f"Ticket body number {i} about a networking outage", "group_key": group})
    processed, rejected = validate_and_process(records, "ticket_labels")
    assert not rejected
    assign_leakage_safe_splits(processed, (0.7, 0.15, 0.15), seed="unit-test-seed")
    by_group: dict[str, set[str]] = {}
    for row in processed:
        by_group.setdefault(row.group_key, set()).add(row.split)
    assert all(len(splits) == 1 for splits in by_group.values())
    assert {row.split for row in processed} <= {"train", "validation", "test"}


_NEAR_DUP_BASE = "the vpn client on this laptop fails to connect to the corporate network gateway during the morning login process for most remote employees"
_NEAR_DUP_VARIANT = _NEAR_DUP_BASE + " again today"


def test_near_duplicate_flagged_only_across_different_splits():
    same_text_a = ProcessedRow(row_index=0, group_key="g1", redacted_text=_NEAR_DUP_BASE, content_hash="a", language_code="en", pii_categories=[], corruption_flags=[], split="train")
    same_text_b = ProcessedRow(row_index=1, group_key="g2", redacted_text=_NEAR_DUP_VARIANT, content_hash="b", language_code="en", pii_categories=[], corruption_flags=[], split="test")
    unrelated = ProcessedRow(row_index=2, group_key="g3", redacted_text="completely unrelated payroll question about benefits enrollment", content_hash="c", language_code="en", pii_categories=[], corruption_flags=[], split="test")
    leaked, skipped = detect_cross_split_near_duplicates([same_text_a, same_text_b, unrelated])
    assert skipped is False
    assert leaked == 1
    assert any(flag.startswith("near_duplicate_cross_split_of_row_0") for flag in same_text_b.corruption_flags)
    assert unrelated.corruption_flags == []


def test_near_duplicate_in_same_split_is_not_counted_as_leakage():
    a = ProcessedRow(row_index=0, group_key="g1", redacted_text=_NEAR_DUP_BASE, content_hash="a", language_code="en", pii_categories=[], corruption_flags=[], split="train")
    b = ProcessedRow(row_index=1, group_key="g2", redacted_text=_NEAR_DUP_VARIANT, content_hash="b", language_code="en", pii_categories=[], corruption_flags=[], split="train")
    leaked, skipped = detect_cross_split_near_duplicates([a, b])
    assert leaked == 0
    assert skipped is False


def test_dataset_version_content_hash_is_order_independent_and_content_sensitive():
    a = ProcessedRow(row_index=0, group_key="g", redacted_text="x", content_hash="hash-a", language_code="en", pii_categories=[], corruption_flags=[], split="train")
    b = ProcessedRow(row_index=1, group_key="g", redacted_text="y", content_hash="hash-b", language_code="en", pii_categories=[], corruption_flags=[], split="test")
    forward = dataset_version_content_hash([a, b])
    backward = dataset_version_content_hash([b, a])
    assert forward == backward
    c = ProcessedRow(row_index=2, group_key="g", redacted_text="z", content_hash="hash-c", language_code="en", pii_categories=[], corruption_flags=[], split="test")
    assert dataset_version_content_hash([a, c]) != forward


@pytest.mark.asyncio(loop_scope="session")
async def test_dataset_import_is_feature_flag_gated_and_permission_checked():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        customer = await token(client, "customer@demo.com")

        denied = await client.post(
            "/api/v2/datasets",
            headers=auth(customer),
            json={"key": "denied_ds", "name": "Denied", "kind": "ticket_labels", "description": "Should be denied by permission before the flag is even checked."},
        )
        assert denied.status_code == 403

        gated = await client.post(
            "/api/v2/datasets",
            headers=auth(admin),
            json={"key": "gated_ds", "name": "Gated", "kind": "ticket_labels", "description": "Should be blocked while evaluation_lab is disabled by default."},
        )
        assert gated.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_dataset_import_creates_leakage_safe_version_with_quality_report_and_reverts(demo_datasets):
    override_id = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        headers = auth(admin)
        current_user = (await client.get("/api/auth/me", headers=headers)).json()
        try:
            override = await client.post(
                "/api/v2/features/evaluation_lab/overrides",
                headers=headers,
                json={"scope_type": "tenant", "scope_value": current_user["tenant_id"], "enabled": True, "rollout_percentage": 100, "reason": "Dataset ingestion test"},
            )
            assert override.status_code == 201, override.text
            override_id = override.json()["id"]

            dataset_resp = await client.post(
                "/api/v2/datasets",
                headers=headers,
                json={"key": "automated_test_ticket_labels", "name": "Automated test dataset", "kind": "ticket_labels", "description": "Created by an automated test to verify leakage-safe splitting end to end."},
            )
            assert dataset_resp.status_code == 201, dataset_resp.text
            dataset_id = dataset_resp.json()["id"]
            demo_datasets.append(dataset_id)

            lines = ["text,department,priority,group_key"]
            for i in range(9):
                group = f"thread-{i // 3}"
                lines.append(f'"VPN connection issue number {i} for the corporate gateway",Networking,high,{group}')
            csv_content = "\n".join(lines)

            import_resp = await client.post(
                f"/api/v2/datasets/{dataset_id}/import",
                headers=headers,
                data={"source_format": "csv", "split_seed": "test-seed"},
                files={"file": ("tickets.csv", csv_content, "text/csv")},
            )
            assert import_resp.status_code == 201, import_resp.text
            body = import_resp.json()
            assert body["version"]["row_count"] == 9
            assert body["version"]["status"] == "ready"
            split_counts = body["quality_report"]["split_counts"]
            assert sum(split_counts.values()) == 9
            version_id = body["version"]["id"]

            rows_resp = await client.get(f"/api/v2/datasets/{dataset_id}/versions/{version_id}/rows", headers=headers, params={"page_size": 50})
            assert rows_resp.status_code == 200
            by_group: dict[str, set[str]] = {}
            for row in rows_resp.json()["items"]:
                by_group.setdefault(row["group_key"], set()).add(row["split"])
            assert all(len(splits) == 1 for splits in by_group.values())

            versions_resp = await client.get(f"/api/v2/datasets/{dataset_id}/versions", headers=headers)
            assert versions_resp.status_code == 200
            assert versions_resp.json()["items"][0]["id"] == version_id

            revert_resp = await client.post(f"/api/v2/datasets/{dataset_id}/versions/{version_id}/revert", headers=headers)
            assert revert_resp.status_code == 200, revert_resp.text
            assert revert_resp.json()["status"] == "reverted"

            rows_after_revert = await client.get(f"/api/v2/datasets/{dataset_id}/versions/{version_id}/rows", headers=headers)
            assert rows_after_revert.json()["total"] == 0
        finally:
            if override_id:
                await client.delete(f"/api/v2/features/evaluation_lab/overrides/{override_id}", headers=headers)
