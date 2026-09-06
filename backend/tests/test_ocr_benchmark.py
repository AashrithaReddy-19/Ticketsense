"""Coverage for the V2 Phase 11 OCR/multimodal diagnostic benchmark lab.

Every metric produced by a completed run must be a real character/word error
rate computed by ai.evaluation.metrics against a real (here, mocked-engine)
extraction — never a fabricated number. An engine that isn't actually
installed (easyocr and paddleocr are genuinely absent from this environment,
and Tesseract's binary is genuinely absent outside the Docker image) must
produce an honest engine_unavailable run, and a mid-run engine failure must
be reported as failed rather than silently skipped or hidden.
"""
import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select, text

from app.database import async_session_maker
from app.main import app
from app.models.ocr_benchmark import OcrBenchmarkDataset, OcrBenchmarkResult, OcrBenchmarkRun
from ai.evaluation.metrics import character_error_rate, word_error_rate
from app.services.ocr.benchmark import add_case, run_benchmark
from app.services.ocr.engines import available_engines
from test_resolution_policy_and_assignment import scenario  # noqa: F401


def tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(buf, format="PNG")
    return buf.getvalue()


async def _dataset(db, scenario, key="ocr-suite"):
    dataset = OcrBenchmarkDataset(tenant_id=scenario["tenant_id"], key=key, name="OCR benchmark suite", created_by=scenario["engineer_id"])
    db.add(dataset)
    await db.flush()
    return dataset


@pytest.mark.asyncio(loop_scope="session")
async def test_available_engines_reports_real_probe_state():
    result = available_engines()
    assert set(result) == {"tesseract", "easyocr", "paddleocr"}
    for engine, info in result.items():
        assert isinstance(info["available"], bool)
        if not info["available"]:
            assert info["reason"]  # a real reason string, never a silent False
    # Genuinely absent from this dev environment (only installed inside the Docker image /
    # never installed at all here) — this assertion documents the honest, unmocked reality.
    assert result["easyocr"]["available"] is False
    assert "not installed" in result["easyocr"]["reason"]
    assert result["paddleocr"]["available"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_engine_unavailable_produces_honest_run_not_fabricated_metrics(scenario):
    async with async_session_maker() as db:
        dataset = await _dataset(db, scenario)
        await db.commit()

        run = await run_benchmark(db, scenario["tenant_id"], dataset.id, "easyocr", scenario["engineer_id"])
        await db.commit()

        assert run.status == "engine_unavailable"
        assert run.unavailable_reason and "not installed" in run.unavailable_reason
        assert run.mean_character_error_rate is None
        assert run.mean_word_error_rate is None
        assert run.row_count_considered == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_insufficient_data_before_minimum_case_count(scenario, monkeypatch):
    monkeypatch.setattr("pytesseract.get_tesseract_version", lambda: "5.0.0")
    async with async_session_maker() as db:
        dataset = await _dataset(db, scenario, key="ocr-small")
        await db.commit()
        await add_case(db, scenario["tenant_id"], dataset.id, scenario["engineer_id"], tiny_png(), "Server unreachable")
        await db.commit()

        run = await run_benchmark(db, scenario["tenant_id"], dataset.id, "tesseract", scenario["engineer_id"])
        await db.commit()

        assert run.status == "insufficient_data"
        assert "at least 3" in run.unavailable_reason
        assert run.row_count_considered == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_completed_run_computes_real_cer_and_wer(scenario, monkeypatch):
    monkeypatch.setattr("pytesseract.get_tesseract_version", lambda: "5.0.0")
    ground_truths = ["Server unreachable after reboot", "VPN handshake timeout error", "Disk quota exceeded on volume C"]
    hypotheses = ["Server unreachable after rebot", "VPN handshake timeout error", "Disk quota exceeded on volme D"]  # deliberately imperfect
    calls = iter(hypotheses)
    monkeypatch.setattr("pytesseract.image_to_string", lambda *a, **k: next(calls))

    async with async_session_maker() as db:
        dataset = await _dataset(db, scenario, key="ocr-real-metrics")
        for truth in ground_truths:
            await add_case(db, scenario["tenant_id"], dataset.id, scenario["engineer_id"], tiny_png(), truth)
        await db.commit()

        run = await run_benchmark(db, scenario["tenant_id"], dataset.id, "tesseract", scenario["engineer_id"])
        await db.commit()

        assert run.status == "completed"
        assert run.row_count_considered == 3
        # Hand-computed: hypothesis and reference are identical for the second case.
        results = (await db.scalars(select(OcrBenchmarkResult).where(OcrBenchmarkResult.run_id == run.id))).all()
        assert len(results) == 3
        exact_match = [r for r in results if float(r.character_error_rate) == 0.0]
        assert len(exact_match) == 1  # only the second (untouched) hypothesis matches exactly

        expected_mean_cer = sum(character_error_rate(h, t) for h, t in zip(hypotheses, ground_truths)) / 3
        expected_mean_wer = sum(word_error_rate(h, t) for h, t in zip(hypotheses, ground_truths)) / 3
        assert float(run.mean_character_error_rate) == pytest.approx(expected_mean_cer, abs=1e-6)
        assert float(run.mean_word_error_rate) == pytest.approx(expected_mean_wer, abs=1e-6)
        assert run.mean_latency_ms is not None and run.mean_latency_ms >= 0


@pytest.mark.asyncio(loop_scope="session")
async def test_mid_run_engine_failure_reported_as_failed_not_skipped(scenario, monkeypatch):
    monkeypatch.setattr("pytesseract.get_tesseract_version", lambda: "5.0.0")
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated OCR crash")
        return "some text"

    monkeypatch.setattr("pytesseract.image_to_string", flaky)

    async with async_session_maker() as db:
        dataset = await _dataset(db, scenario, key="ocr-flaky")
        for i in range(3):
            await add_case(db, scenario["tenant_id"], dataset.id, scenario["engineer_id"], tiny_png(), f"Ground truth {i}")
        await db.commit()

        run = await run_benchmark(db, scenario["tenant_id"], dataset.id, "tesseract", scenario["engineer_id"])
        await db.commit()

        assert run.status == "failed"
        assert "simulated OCR crash" in run.unavailable_reason
        assert run.mean_character_error_rate is None  # never averaged over a partial, failed run


async def _token(client, email, password="Demo@123") -> str:
    resp = await client.post("/api/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_ocr_benchmark_endpoints_are_feature_flag_gated_then_work():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {await _token(client, 'sysadmin@demo.com')}"}
        me = await client.get("/api/auth/me", headers=headers)
        tenant_id = me.json()["tenant_id"]

        gated = await client.get("/api/v2/ocr-benchmark/engines", headers=headers)
        assert gated.status_code == 404

        override = await client.post(
            "/api/v2/features/multimodal_analysis/overrides", headers=headers,
            json={"scope_type": "tenant", "scope_value": tenant_id, "enabled": True, "rollout_percentage": 100, "reason": "OCR benchmark lab test"},
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]
        dataset_id = None
        try:
            engines = await client.get("/api/v2/ocr-benchmark/engines", headers=headers)
            assert engines.status_code == 200
            engine_info = engines.json()["engines"]
            assert set(engine_info) == {"tesseract", "easyocr", "paddleocr"}
            assert engine_info["easyocr"]["available"] is False  # honest, unmocked state over the real API

            created = await client.post("/api/v2/ocr-benchmark/datasets", headers=headers, json={"key": "e2e-ocr-suite", "name": "E2E OCR suite"})
            assert created.status_code == 201, created.text
            dataset_id = created.json()["id"]

            listing = await client.get("/api/v2/ocr-benchmark/datasets", headers=headers)
            assert listing.status_code == 200
            assert any(d["id"] == dataset_id for d in listing.json()["items"])

            import base64
            case = await client.post(
                f"/api/v2/ocr-benchmark/datasets/{dataset_id}/cases", headers=headers,
                json={"image_base64": base64.b64encode(tiny_png()).decode(), "ground_truth_text": "Printer offline"},
            )
            assert case.status_code == 201, case.text

            run = await client.post("/api/v2/ocr-benchmark/runs", headers=headers, json={"dataset_id": dataset_id, "engine": "tesseract"})
            assert run.status_code == 201, run.text
            # Tesseract's binary is genuinely absent in this dev environment (only installed in the
            # Docker image) — the real API honestly reports engine_unavailable rather than any score.
            assert run.json()["status"] == "engine_unavailable"
            assert run.json()["mean_character_error_rate"] is None
        finally:
            await client.delete(f"/api/v2/features/multimodal_analysis/overrides/{override_id}", headers=headers)
            if dataset_id:
                async with async_session_maker() as db:
                    await db.execute(text("DELETE FROM ocr_benchmark_datasets WHERE id=:d"), {"d": dataset_id})
                    await db.commit()
