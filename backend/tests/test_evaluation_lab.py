import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.evaluation.metrics import classification_report_exact


async def token(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", data={"username": email, "password": "Demo@123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


# Hand-verifiable fixture: y_true vs y_pred differ on exactly one of four rows.
# Correct: (a,a), (b,b), (b,b); wrong: (a,b). accuracy = 3/4.
# Class a: predicted once ("a"), correctly -> precision 1.0; true a=2, one caught -> recall 0.5.
# Class b: predicted three times, two correct -> precision 2/3; true b=2, both caught -> recall 1.0.
def test_classification_metrics_match_hand_computed_fixture():
    report = classification_report_exact(["a", "a", "b", "b"], ["a", "b", "b", "b"], ["a", "b"])
    assert report["accuracy"] == pytest.approx(0.75)
    assert report["per_class"]["a"] == {"precision": 1.0, "recall": 0.5, "f1": pytest.approx(2 / 3), "support": 2}
    assert report["per_class"]["b"] == {"precision": pytest.approx(2 / 3), "recall": 1.0, "f1": 0.8, "support": 2}
    assert report["overall"]["macro"]["precision"] == pytest.approx((1.0 + 2 / 3) / 2)
    assert report["overall"]["micro"]["precision"] == pytest.approx(0.75)
    assert report["confusion_matrix"]["labels"] == ["a", "b"]
    assert report["confusion_matrix"]["matrix"] == [[1, 1], [0, 2]]


def test_classification_metrics_requires_at_least_one_example():
    with pytest.raises(ValueError):
        classification_report_exact([], [], ["a", "b"])


def test_top_k_accuracy_uses_real_probabilities():
    # True label is always within the top-2 highest-probability classes here.
    report = classification_report_exact(
        ["a", "b", "c"], ["a", "a", "c"],
        ["a", "b", "c"],
        y_proba=[[0.6, 0.3, 0.1], [0.5, 0.4, 0.1], [0.2, 0.3, 0.5]],
        proba_classes=["a", "b", "c"],
    )
    assert report["top_k_accuracy"]["top_2_accuracy"] == 1.0


@pytest.mark.asyncio(loop_scope="session")
async def test_evaluation_run_requires_evaluation_lab_flag_and_permission():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        customer = await token(client, "customer@demo.com")

        denied = await client.get("/api/v2/evaluation/runs", headers=auth(customer))
        assert denied.status_code == 403

        gated = await client.get("/api/v2/evaluation/runs", headers=auth(admin))
        assert gated.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_evaluation_run_below_minimum_sample_size_reports_insufficient_data(demo_datasets):
    override_id = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        headers = auth(admin)
        current_user = (await client.get("/api/auth/me", headers=headers)).json()
        try:
            override = await client.post(
                "/api/v2/features/evaluation_lab/overrides", headers=headers,
                json={"scope_type": "tenant", "scope_value": current_user["tenant_id"], "enabled": True, "rollout_percentage": 100, "reason": "Evaluation lab test"},
            )
            assert override.status_code == 201, override.text
            override_id = override.json()["id"]

            dataset_resp = await client.post(
                "/api/v2/datasets", headers=headers,
                json={"key": "tiny_eval_ds", "name": "Tiny eval dataset", "kind": "ticket_labels", "description": "Deliberately below the minimum evaluation sample size."},
            )
            assert dataset_resp.status_code == 201, dataset_resp.text
            dataset_id = dataset_resp.json()["id"]
            demo_datasets.append(dataset_id)

            csv_content = "text,department\n\"VPN gateway is unreachable from the office\",Networking\n\"SAP transport failed with error ST22\",SAP\n"
            import_resp = await client.post(
                f"/api/v2/datasets/{dataset_id}/import", headers=headers,
                data={"source_format": "csv", "split_seed": "tiny", "train_ratio": "0", "validation_ratio": "0", "test_ratio": "1"},
                files={"file": ("tiny.csv", csv_content, "text/csv")},
            )
            assert import_resp.status_code == 201, import_resp.text
            version_id = import_resp.json()["version"]["id"]

            run_resp = await client.post("/api/v2/evaluation/runs", headers=headers, json={"dataset_version_id": version_id, "target": "department"})
            assert run_resp.status_code == 201, run_resp.text
            body = run_resp.json()
            assert body["status"] == "insufficient_data"
            assert body["row_count_considered"] < 5
        finally:
            if override_id:
                await client.delete(f"/api/v2/features/evaluation_lab/overrides/{override_id}", headers=headers)


@pytest.mark.asyncio(loop_scope="session")
async def test_evaluation_run_computes_real_metrics_against_trained_classifier(demo_datasets):
    override_id = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await token(client, "sysadmin@demo.com")
        headers = auth(admin)
        current_user = (await client.get("/api/auth/me", headers=headers)).json()
        try:
            override = await client.post(
                "/api/v2/features/evaluation_lab/overrides", headers=headers,
                json={"scope_type": "tenant", "scope_value": current_user["tenant_id"], "enabled": True, "rollout_percentage": 100, "reason": "Evaluation lab test"},
            )
            assert override.status_code == 201, override.text
            override_id = override.json()["id"]

            dataset_resp = await client.post(
                "/api/v2/datasets", headers=headers,
                json={"key": "department_eval_ds", "name": "Department eval dataset", "kind": "ticket_labels", "description": "Automated test dataset for the department classifier evaluation run."},
            )
            assert dataset_resp.status_code == 201, dataset_resp.text
            dataset_id = dataset_resp.json()["id"]
            demo_datasets.append(dataset_id)

            # Labels use the trained classifier's real class names (Cloud, HR, Networking, SAP)
            # so none of these rows are excluded as a label-space mismatch.
            rows = [
                ("VPN connection keeps dropping and DNS lookups fail on the office network", "Networking"),
                ("Firewall is blocking the new proxy configuration for remote staff", "Networking"),
                ("EC2 instance will not boot and the S3 bucket policy looks wrong", "Cloud"),
                ("IAM role permissions are misconfigured for the new cloud storage bucket", "Cloud"),
                ("SAP transport TCODE failed with ST22 dump during the purchase order run", "SAP"),
                ("IDoc processing is stuck and the SAP purchase order will not post", "SAP"),
                ("Employee payroll timesheet was not submitted before the benefits deadline", "HR"),
                ("Onboarding leave request and payroll benefit enrollment is stuck", "HR"),
            ]
            lines = ["text,department"] + [f'"{text}",{dept}' for text, dept in rows]
            import_resp = await client.post(
                f"/api/v2/datasets/{dataset_id}/import", headers=headers,
                data={"source_format": "csv", "split_seed": "dept-eval", "train_ratio": "0", "validation_ratio": "0", "test_ratio": "1"},
                files={"file": ("department.csv", "\n".join(lines), "text/csv")},
            )
            assert import_resp.status_code == 201, import_resp.text
            version_id = import_resp.json()["version"]["id"]

            run_resp = await client.post("/api/v2/evaluation/runs", headers=headers, json={"dataset_version_id": version_id, "target": "department"})
            assert run_resp.status_code == 201, run_resp.text
            run = run_resp.json()
            assert run["status"] == "completed"
            assert run["row_count_considered"] >= 5
            assert run["model_artifact_hash"] is not None
            assert run["git_commit"] is None or len(run["git_commit"]) == 40

            detail = await client.get(f"/api/v2/evaluation/runs/{run['id']}", headers=headers)
            assert detail.status_code == 200, detail.text
            detail_body = detail.json()
            assert 0.0 <= detail_body["overall_metrics"]["accuracy"] <= 1.0
            assert detail_body["confusion_matrix"] is not None
            assert set(detail_body["confusion_matrix"]["labels"]) <= {"Cloud", "HR", "Networking", "SAP"}

            examples = await client.get(f"/api/v2/evaluation/runs/{run['id']}/examples", headers=headers)
            assert examples.status_code == 200
            assert examples.json()["total"] == run["row_count_considered"]
            assert all(item["redacted_text"] for item in examples.json()["items"])

            wrong_only = await client.get(f"/api/v2/evaluation/runs/{run['id']}/examples", headers=headers, params={"correct": "false"})
            assert wrong_only.status_code == 200
            assert all(item["correct"] is False for item in wrong_only.json()["items"])

            export = await client.get(f"/api/v2/evaluation/runs/{run['id']}/export", headers=headers)
            assert export.status_code == 200
            assert len(export.json()["examples"]) == run["row_count_considered"]
        finally:
            if override_id:
                await client.delete(f"/api/v2/features/evaluation_lab/overrides/{override_id}", headers=headers)
