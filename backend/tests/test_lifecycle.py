"""The producer journey, driven through the HTTP API exactly as the UI does."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import schema_columns

PRODUCT = {
    "templateId": "dataproduct-standard",
    "values": {
        "name": "customer-360",
        "displayName": "Customer 360",
        "domain": "sales",
        "description": "A deduplicated view of every customer, refreshed daily for analytics teams.",
        "email": "sales-data@acme.io",
        "maturity": "tactical",
        "informationSLA": "8h",
        "tags": ["customer", "gold"],
    },
}

STORAGE = {
    "templateId": "storage-delta-lake",
    "values": {
        "name": "customer-master", "description": "Curated table, one row per customer.",
        "catalog": "lakehouse", "dbSchema": "sales", "table": "customer_master",
        "partitionBy": ["country"], "zOrderBy": [], "retentionDays": 30,
    },
}

PORT = {
    "templateId": "outputport-snowflake-table",
    "values": {
        "name": "customer-snapshot", "description": "Daily snapshot for BI.",
        "database": "ANALYTICS", "dbSchema": "SALES", "table": "CUSTOMER_SNAPSHOT", "warehouse": "WH_SMALL",
        "columns": schema_columns(
            ("customer_id", "string", "Stable key.", False, False, "internal"),
            ("email", "string", "Contact address.", True, True, "confidential"),
        ),
        "intervalOfChange": "1 day", "timeliness": "2 hours", "upTime": "99.9%",
        "termsAndConditions": "Personal data may not leave the EU.",
        "tags": ["pii"],
    },
}

OBSERVABILITY = {
    "templateId": "observability-data-quality",
    "values": {
        "name": "snapshot-quality", "description": "Checks freshness and volume.",
        "monitors": "customer-snapshot", "freshnessMinutes": 120, "minRowCount": 1000,
        "nullThresholdPercent": 1, "checkSchemaDrift": True, "channel": "#alerts", "severity": "high",
    },
}


def create_product(client: TestClient, headers: dict) -> dict:
    response = client.post("/api/dataproducts", json=PRODUCT, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_scaffolding_creates_repository_descriptor_and_catalog_entry(client, auth):
    headers = auth("alice")
    dp = create_product(client, headers)

    assert dp["urn"] == "urn:dmp:sales:customer-360:0"
    assert dp["lifecycle"] == "draft"

    descriptor = client.get(f"/api/dataproducts/{dp['id']}/descriptor", headers=headers).json()
    assert descriptor["parsed"]["metadata"]["owner"] == "user:alice"

    repository = client.get(f"/api/dataproducts/{dp['id']}/repository", headers=headers).json()
    assert "data-product-descriptor.yaml" in repository["files"]
    assert repository["commits"][0]["message"].startswith("feat: scaffold")


def test_the_same_data_product_cannot_be_created_twice(client, auth):
    headers = auth("alice")
    create_product(client, headers)
    response = client.post("/api/dataproducts", json=PRODUCT, headers=headers)
    assert response.status_code == 409


def test_full_journey_from_draft_to_marketplace(client, auth):
    headers = auth("alice")
    dp = create_product(client, headers)
    dp_id = dp["id"]

    # a product with no output port is blocked from release
    blocked = client.post(f"/api/dataproducts/{dp_id}/release", json={"version": "1.0.0"}, headers=headers)
    assert blocked.status_code == 409

    for payload in (STORAGE, PORT, OBSERVABILITY):
        response = client.post(f"/api/dataproducts/{dp_id}/components", json=payload, headers=headers)
        assert response.status_code == 201, response.text

    report = client.post(f"/api/dataproducts/{dp_id}/validate", headers=headers).json()
    assert report["passed"], report["findings"]

    # publishing before a release is refused
    assert client.post(f"/api/dataproducts/{dp_id}/publish", headers=headers).status_code == 409

    released = client.post(
        f"/api/dataproducts/{dp_id}/release", json={"version": "1.0.0", "notes": "First."}, headers=headers
    )
    assert released.status_code == 200, released.text
    assert released.json()["dataProduct"]["lifecycle"] == "released"
    # the major version is part of the identity, so the URN moves with it
    assert released.json()["dataProduct"]["urn"] == "urn:dmp:sales:customer-360:1"

    # ...and publishing still needs the product to actually run in production
    assert client.post(f"/api/dataproducts/{dp_id}/publish", headers=headers).status_code == 409

    deployment = client.post(
        f"/api/dataproducts/{dp_id}/deployments", json={"environment": "production"}, headers=headers
    )
    assert deployment.status_code == 201, deployment.text
    body = deployment.json()
    assert body["status"] == "provisioned"
    assert body["outputs"]["customer-snapshot"]["objectName"] == "PRD_ANALYTICS.SALES.CUSTOMER_SNAPSHOT"

    published = client.post(f"/api/dataproducts/{dp_id}/publish", headers=headers)
    assert published.status_code == 200
    assert published.json()["lifecycle"] == "published"

    listing = client.get("/api/marketplace", headers=auth("bruno")).json()
    assert [item["urn"] for item in listing["items"]] == ["urn:dmp:sales:customer-360:1"]


def test_components_are_provisioned_in_dependency_order(client, auth):
    headers = auth("alice")
    dp_id = create_product(client, headers)["id"]
    for payload in (PORT, OBSERVABILITY, STORAGE):  # deliberately added out of order
        client.post(f"/api/dataproducts/{dp_id}/components", json=payload, headers=headers)

    plan = client.post(
        f"/api/dataproducts/{dp_id}/deployments/plan?environment=development", headers=headers
    ).json()
    assert [step["component"] for step in plan["steps"]] == [
        "customer-master", "customer-snapshot", "snapshot-quality",
    ]
    assert plan["problems"] == []


def test_a_draft_cannot_be_provisioned_to_production(client, auth):
    headers = auth("alice")
    dp_id = create_product(client, headers)["id"]
    for payload in (STORAGE, PORT, OBSERVABILITY):
        client.post(f"/api/dataproducts/{dp_id}/components", json=payload, headers=headers)

    assert client.post(
        f"/api/dataproducts/{dp_id}/deployments", json={"environment": "development"}, headers=headers
    ).status_code == 201
    refused = client.post(
        f"/api/dataproducts/{dp_id}/deployments", json={"environment": "production"}, headers=headers
    )
    assert refused.status_code == 409
    assert "release" in refused.json()["detail"]


def test_governance_blocks_production_when_a_policy_fails(client, auth):
    headers = auth("alice")
    dp_id = create_product(client, headers)["id"]
    leaky = {**PORT, "values": {**PORT["values"], "columns": schema_columns(
        ("email", "string", "Contact.", True, True, "internal"),
    )}}
    client.post(f"/api/dataproducts/{dp_id}/components", json=STORAGE, headers=headers)
    client.post(f"/api/dataproducts/{dp_id}/components", json=leaky, headers=headers)

    report = client.post(f"/api/dataproducts/{dp_id}/validate", headers=headers).json()
    assert not report["passed"]
    assert any(f["policyId"] == "pii-protected" for f in report["findings"])


def test_only_the_owner_may_change_a_data_product(client, auth):
    dp_id = create_product(client, auth("alice"))["id"]
    response = client.post(
        f"/api/dataproducts/{dp_id}/components", json=STORAGE, headers=auth("bruno")
    )
    assert response.status_code == 403


def test_the_descriptor_is_frozen_while_under_review(client, auth):
    headers = auth("alice")
    dp_id = create_product(client, headers)["id"]
    for payload in (STORAGE, PORT, OBSERVABILITY):
        client.post(f"/api/dataproducts/{dp_id}/components", json=payload, headers=headers)

    assert client.post(f"/api/dataproducts/{dp_id}/submit", headers=headers).status_code == 200
    frozen = client.post(f"/api/dataproducts/{dp_id}/components", json=OBSERVABILITY, headers=headers)
    assert frozen.status_code == 409
    assert "frozen" in frozen.json()["detail"]


def test_editing_the_descriptor_commits_and_re_ingests(client, auth):
    headers = auth("alice")
    dp_id = create_product(client, headers)["id"]
    current = client.get(f"/api/dataproducts/{dp_id}/descriptor", headers=headers).json()["content"]

    updated = current.replace("informationSLA: 8h", "informationSLA: 4h")
    response = client.put(
        f"/api/dataproducts/{dp_id}/descriptor",
        json={"content": updated, "message": "docs: tighten the SLA"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["parsed"]["metadata"]["informationSLA"] == "4h"

    commits = client.get(f"/api/dataproducts/{dp_id}/repository", headers=headers).json()["commits"]
    assert commits[0]["message"] == "docs: tighten the SLA"


def test_renaming_a_data_product_through_the_descriptor_is_refused(client, auth):
    headers = auth("alice")
    dp_id = create_product(client, headers)["id"]
    current = client.get(f"/api/dataproducts/{dp_id}/descriptor", headers=headers).json()["content"]

    response = client.put(
        f"/api/dataproducts/{dp_id}/descriptor",
        json={"content": current.replace("name: customer-360", "name: customer-720")},
        headers=headers,
    )
    assert response.status_code == 409
    assert "immutable" in response.json()["detail"]


def test_invalid_yaml_is_rejected_with_useful_detail(client, auth):
    headers = auth("alice")
    dp_id = create_product(client, headers)["id"]
    response = client.put(
        f"/api/dataproducts/{dp_id}/descriptor", json={"content": "metadata: name: broken:"}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"] == "Invalid descriptor"
