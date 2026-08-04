"""Discovery, access and lineage from the consumer's side."""

from __future__ import annotations

from tests.test_lifecycle import OBSERVABILITY, PORT, PRODUCT, STORAGE


def publish_customer_360(client, auth) -> tuple[int, dict]:
    headers = auth("alice")
    dp = client.post("/api/dataproducts", json=PRODUCT, headers=headers).json()
    for payload in (STORAGE, PORT, OBSERVABILITY):
        client.post(f"/api/dataproducts/{dp['id']}/components", json=payload, headers=headers)
    client.post(f"/api/dataproducts/{dp['id']}/release", json={"version": "1.0.0"}, headers=headers)
    client.post(f"/api/dataproducts/{dp['id']}/deployments", json={"environment": "production"}, headers=headers)
    client.post(f"/api/dataproducts/{dp['id']}/publish", headers=headers)
    return dp["id"], headers


def test_only_published_products_are_discoverable(client, auth):
    alice = auth("alice")
    draft = client.post("/api/dataproducts", json=PRODUCT, headers=alice).json()
    assert client.get("/api/marketplace", headers=auth("bruno")).json()["total"] == 0
    # ...and the detail endpoint does not leak them either
    assert client.get(f"/api/marketplace/{draft['id']}", headers=auth("bruno")).status_code == 404


def test_facets_describe_what_is_available(client, auth):
    publish_customer_360(client, auth)
    listing = client.get("/api/marketplace", headers=auth("bruno")).json()
    assert listing["facets"]["domains"] == [{"value": "sales", "count": 1}]
    assert listing["facets"]["technologies"] == [{"value": "snowflake", "count": 1}]
    assert {"value": "customer", "count": 1} in listing["facets"]["tags"]


def test_the_endpoint_is_hidden_until_access_is_granted(client, auth):
    dp_id, _ = publish_customer_360(client, auth)
    bruno = auth("bruno")

    detail = client.get(f"/api/marketplace/{dp_id}", headers=bruno).json()
    port = detail["outputPorts"][0]
    assert port["access"] == "none"
    # the contract itself is public — that is the point of the marketplace
    assert port["columnCount"] == 2
    assert port["dataContract"]["schema"][1]["pii"] is True


def test_access_is_requested_decided_and_revoked(client, auth):
    dp_id, alice = publish_customer_360(client, auth)
    bruno = auth("bruno")

    port_id = client.get(f"/api/marketplace/{dp_id}", headers=bruno).json()["outputPorts"][0]["id"]
    created = client.post(
        f"/api/marketplace/{dp_id}/access-requests",
        json={"componentId": port_id, "purpose": "Build the weekly revenue dashboard."},
        headers=bruno,
    )
    assert created.status_code == 201
    request_id = created.json()["id"]

    # asking twice for the same port is refused while one is outstanding
    duplicate = client.post(
        f"/api/marketplace/{dp_id}/access-requests",
        json={"componentId": port_id, "purpose": "Same thing again, honestly."},
        headers=bruno,
    )
    assert duplicate.status_code == 409

    # a stranger cannot decide on somebody else's data product
    assert client.post(
        f"/api/marketplace/access-requests/{request_id}/decision", json={"approve": True}, headers=bruno
    ).status_code == 403

    inbox = client.get("/api/marketplace/access-requests/inbox", headers=alice).json()
    assert [r["id"] for r in inbox] == [request_id]

    approved = client.post(
        f"/api/marketplace/access-requests/{request_id}/decision",
        json={"approve": True, "note": "Approved for reporting."},
        headers=alice,
    )
    assert approved.json()["status"] == "approved"

    detail = client.get(f"/api/marketplace/{dp_id}", headers=bruno).json()
    assert detail["outputPorts"][0]["access"] == "approved"
    assert len(client.get("/api/marketplace/me/subscriptions", headers=bruno).json()) == 1

    revoked = client.post(f"/api/marketplace/access-requests/{request_id}/revoke", headers=alice)
    assert revoked.json()["status"] == "revoked"
    assert client.get("/api/marketplace/me/subscriptions", headers=bruno).json() == []


def test_an_owner_cannot_request_access_to_their_own_product(client, auth):
    dp_id, alice = publish_customer_360(client, auth)
    port_id = client.get(f"/api/marketplace/{dp_id}", headers=alice).json()["outputPorts"][0]["id"]
    response = client.post(
        f"/api/marketplace/{dp_id}/access-requests",
        json={"componentId": port_id, "purpose": "I would like to use my own data."},
        headers=alice,
    )
    assert response.status_code == 409


def test_a_dependency_shows_up_in_the_lineage_graph(client, auth):
    dp_id, _ = publish_customer_360(client, auth)
    maya = auth("bruno")

    ports = client.get("/api/marketplace/output-ports/published", headers=maya).json()
    port_urn = ports[0]["urn"]

    downstream = client.post(
        "/api/dataproducts",
        json={
            "templateId": "dataproduct-standard",
            "values": {
                "name": "campaign-attribution", "displayName": "Campaign Attribution", "domain": "marketing",
                "description": "Attributes revenue to campaigns using the customer snapshot as an input.",
                "email": "marketing@acme.io", "maturity": "tactical", "informationSLA": "24h", "tags": [],
            },
        },
        headers=maya,
    ).json()

    added = client.post(
        f"/api/dataproducts/{downstream['id']}/dependencies", json={"portUrn": port_urn}, headers=maya
    )
    assert added.status_code == 201

    graph = client.get("/api/lineage", headers=maya).json()
    edge = next(e for e in graph["edges"] if e["port"] == port_urn)
    assert edge["resolved"] is True
    assert edge["target"] == downstream["urn"]
    assert len(graph["nodes"]) == 2

    # depending on something that is not published at all is refused outright
    refused = client.post(
        f"/api/dataproducts/{downstream['id']}/dependencies",
        json={"portUrn": "urn:dmp:crm:orders:0:events"},
        headers=maya,
    )
    assert refused.status_code == 409
    assert dp_id  # the upstream product is the one we published above
