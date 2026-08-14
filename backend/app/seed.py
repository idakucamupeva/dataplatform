"""Seed the platform with a small but complete mesh.

Everything below goes through the same service functions the API uses, so the
demo data exercises scaffolding, git commits, policy evaluation, provisioning
and publishing exactly as a user would.

    python -m app.seed --reset
"""

from __future__ import annotations

import argparse
import shutil
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.db import Base, SessionLocal, engine, init_db
from app.core.security import hash_password
from app.models import Domain, Role, User
from app.services import dataproducts, github, marketplace, provisioning
from app.services.descriptor_io import serialize

PASSWORD = "password123"

USERS = [
    ("admin", "admin@acme.io", "Ada Admin", Role.ADMIN),
    ("gwen", "gwen@acme.io", "Gwen Governance", Role.GOVERNANCE),
    ("alice", "alice@acme.io", "Alice Producer", Role.USER),
    ("bruno", "bruno@acme.io", "Bruno Consumer", Role.USER),
    ("maya", "maya@acme.io", "Maya Marketing", Role.USER),
]

DOMAINS = [
    ("sales", "Sales", "Everything about orders, customers and the funnel.", "alice"),
    ("marketing", "Marketing", "Campaigns, channels and attribution.", "maya"),
    ("finance", "Finance", "Revenue, cost and regulatory reporting.", "admin"),
    ("logistics", "Logistics", "Warehousing, shipping and delivery promises.", "admin"),
]


def _columns(*rows) -> list[dict]:
    return [
        {
            "name": name,
            "dataType": data_type,
            "description": description,
            "nullable": nullable,
            "pii": pii,
            "classification": classification,
        }
        for name, data_type, description, nullable, pii, classification in rows
    ]


# the repositories this script creates, so --reset can clean them up on GitHub too
DEMO_SLUGS = [
    "sales__customer-360",
    "sales__order-events",
    "marketing__campaign-attribution",
    "finance__revenue-reporting",
    "logistics__delivery-promise",
]


def reset() -> None:
    Base.metadata.drop_all(bind=engine)
    client = github.get_client()
    if client is not None:
        for slug in DEMO_SLUGS:
            name = client.repo_name(slug)
            try:
                if client.repo_exists(name) and client.delete_repo(name):
                    print(f"  deleted GitHub repository {client.owner}/{name}")
            except Exception as exc:  # noqa: BLE001 - reset stays best-effort
                print(f"  ! could not delete {client.owner}/{name}: {exc}")
    shutil.rmtree(settings.repos_dir, ignore_errors=True)
    shutil.rmtree(settings.workspaces_dir, ignore_errors=True)
    settings.ensure_dirs()


def seed() -> None:  # noqa: PLR0915 - a linear script reads better than helpers here
    init_db()
    db = SessionLocal()
    try:
        if db.execute(select(User)).scalars().first():
            print("database already seeded — pass --reset to start over")
            return

        users: dict[str, User] = {}
        for username, email, full_name, role in USERS:
            user = User(
                username=username,
                email=email,
                full_name=full_name,
                hashed_password=hash_password(PASSWORD),
                role=role,
            )
            db.add(user)
            users[username] = user
        db.flush()

        for name, title, description, owner in DOMAINS:
            db.add(Domain(name=name, title=title, description=description, owner_id=users[owner].id))
        db.flush()

        alice, maya, bruno, gwen = users["alice"], users["maya"], users["bruno"], users["gwen"]

        # ------------------------------------------------------------------
        # 1. sales / customer-360 — the full journey to the marketplace
        # ------------------------------------------------------------------
        customer360 = dataproducts.scaffold(
            db,
            template_id="dataproduct-standard",
            values={
                "name": "customer-360",
                "displayName": "Customer 360",
                "domain": "sales",
                "description": (
                    "A single, deduplicated view of every customer: identity, lifetime value, "
                    "channel preferences and current subscription state."
                ),
                "email": "sales-data@acme.io",
                "maturity": "strategic",
                "informationSLA": "8h",
                "tags": ["customer", "gold", "gdpr"],
            },
            owner=alice,
        )
        dataproducts.add_component(
            db, customer360, template_id="storage-delta-lake", actor=alice,
            values={
                "name": "customer-master",
                "displayName": "Customer Master",
                "description": "Curated Delta table holding one row per customer.",
                "catalog": "lakehouse",
                "dbSchema": "sales",
                "table": "customer_master",
                "partitionBy": ["country"],
                "zOrderBy": ["customer_id"],
                "retentionDays": 90,
            },
        )
        dataproducts.add_component(
            db, customer360, template_id="workload-dbt-model", actor=alice,
            values={
                "name": "build-customer-master",
                "displayName": "Build Customer Master",
                "description": "Resolves identities across CRM, billing and web analytics.",
                "materialization": "incremental",
                "targetSchema": "sales",
                "sources": ["raw.crm_customers", "raw.billing_accounts"],
                "schedule": "0 4 * * *",
                "tests": True,
            },
        )
        dataproducts.add_component(
            db, customer360, template_id="outputport-snowflake-table", actor=alice,
            values={
                "name": "customer-snapshot",
                "displayName": "Customer Snapshot",
                "description": "Daily snapshot of the customer master, ready for BI and analytics.",
                "database": "ANALYTICS",
                "dbSchema": "SALES",
                "table": "CUSTOMER_SNAPSHOT",
                "warehouse": "WH_MEDIUM",
                "columns": _columns(
                    ("customer_id", "string", "Stable surrogate key of the customer.", False, False, "internal"),
                    ("email", "string", "Primary contact address.", True, True, "confidential"),
                    ("country", "string", "ISO 3166-1 alpha-2 country of residence.", True, False, "internal"),
                    ("segment", "string", "Value segment: bronze, silver or gold.", True, False, "internal"),
                    ("lifetime_value", "decimal", "Gross margin generated to date, in EUR.", True, False, "confidential"),
                    ("subscribed_at", "timestamp", "When the current subscription started.", True, False, "internal"),
                ),
                "intervalOfChange": "1 day",
                "timeliness": "2 hours",
                "upTime": "99.9%",
                "termsAndConditions": (
                    "Personal data is processed under the customer contract. Do not join with "
                    "third-party identifiers and do not export outside the EU."
                ),
                "tags": ["pii", "gdpr"],
            },
        )
        dataproducts.add_component(
            db, customer360, template_id="observability-data-quality", actor=alice,
            values={
                "name": "snapshot-quality",
                "displayName": "Snapshot Quality",
                "description": "Verifies freshness, volume and schema stability of the customer snapshot.",
                "monitors": "customer-snapshot",
                "freshnessMinutes": 120,
                "minRowCount": 100000,
                "nullThresholdPercent": 1,
                "checkSchemaDrift": True,
                "channel": "#sales-data-alerts",
                "severity": "high",
            },
        )
        # a hand edit of the descriptor, exactly as the YAML editor would submit it
        descriptor = dataproducts.read_descriptor(customer360)
        descriptor.metadata.information_sla = "4h"
        dataproducts.save_descriptor(
            db, customer360, serialize(descriptor), alice, "docs: tighten the information SLA to 4h"
        )

        dataproducts.submit_for_review(db, customer360, alice)
        dataproducts.release(
            db, customer360, version="1.0.0",
            notes="First stable release of the customer snapshot contract.", actor=gwen,
        )
        provisioning.deploy(db, customer360, environment="development", actor=alice)
        provisioning.deploy(db, customer360, environment="production", actor=alice)
        dataproducts.publish(db, customer360, alice)

        # ------------------------------------------------------------------
        # 2. sales / order-events — a streaming product
        # ------------------------------------------------------------------
        orders = dataproducts.scaffold(
            db,
            template_id="dataproduct-standard",
            values={
                "name": "order-events",
                "displayName": "Order Events",
                "domain": "sales",
                "description": (
                    "Every state change of an order, published as it happens, so downstream "
                    "domains can react without polling the order database."
                ),
                "email": "sales-data@acme.io",
                "maturity": "strategic",
                "informationSLA": "4h",
                "tags": ["orders", "streaming", "realtime"],
            },
            owner=alice,
        )
        dataproducts.add_component(
            db, orders, template_id="storage-s3-bucket", actor=alice,
            values={
                "name": "event-archive",
                "displayName": "Event Archive",
                "description": "Immutable archive of every published event, for replay and audit.",
                "region": "eu-central-1",
                "format": "avro",
                "retentionDays": 1095,
                "encryption": "aws:kms",
                "versioning": True,
            },
        )
        dataproducts.add_component(
            db, orders, template_id="outputport-kafka-topic", actor=alice,
            values={
                "name": "order-stream",
                "displayName": "Order Stream",
                "description": "Order lifecycle events keyed by order id.",
                "topic": "sales.order.events.v1",
                "partitions": 12,
                "replication": 3,
                "retentionHours": 336,
                "cleanupPolicy": "delete",
                "keyField": "order_id",
                "columns": _columns(
                    ("order_id", "string", "Identifier of the order.", False, False, "internal"),
                    ("customer_id", "string", "Customer the order belongs to.", False, False, "internal"),
                    ("status", "string", "placed, paid, shipped, delivered or cancelled.", False, False, "internal"),
                    ("total_amount", "double", "Order total including tax, in EUR.", True, False, "internal"),
                    ("occurred_at", "long", "Event time, epoch millis.", False, False, "internal"),
                ),
                "timeliness": "5 seconds",
                "upTime": "99.95%",
                "termsAndConditions": "At-least-once delivery; consumers must be idempotent.",
            },
        )
        dataproducts.add_component(
            db, orders, template_id="workload-airflow-dag", actor=alice,
            values={
                "name": "archive-events",
                "displayName": "Archive Events",
                "description": "Compacts the event stream into the S3 archive every hour.",
                "schedule": "@hourly",
                "retries": 3,
                "slaMinutes": 30,
                "writesTo": "event-archive",
                "readsFrom": [],
            },
        )
        dataproducts.add_component(
            db, orders, template_id="observability-data-quality", actor=alice,
            values={
                "name": "stream-health",
                "displayName": "Stream Health",
                "description": "Watches lag, throughput and schema compatibility of the order stream.",
                "monitors": "order-stream",
                "freshnessMinutes": 5,
                "minRowCount": 1,
                "nullThresholdPercent": 0,
                "checkSchemaDrift": True,
                "channel": "#sales-data-alerts",
                "severity": "critical",
            },
        )
        dataproducts.release(db, orders, version="1.0.0", notes="Initial streaming contract.", actor=alice)
        provisioning.deploy(db, orders, environment="development", actor=alice)
        provisioning.deploy(db, orders, environment="production", actor=alice)
        dataproducts.publish(db, orders, alice)

        # ------------------------------------------------------------------
        # 3. marketing / campaign-attribution — a consumer of the two above
        # ------------------------------------------------------------------
        attribution = dataproducts.scaffold(
            db,
            template_id="dataproduct-standard",
            values={
                "name": "campaign-attribution",
                "displayName": "Campaign Attribution",
                "domain": "marketing",
                "description": (
                    "Attributes revenue to marketing campaigns using a data-driven model, so "
                    "channel budgets can be compared on the same basis."
                ),
                "email": "marketing-data@acme.io",
                "maturity": "tactical",
                "informationSLA": "24h",
                "tags": ["marketing", "attribution", "revenue"],
            },
            owner=maya,
        )
        dataproducts.add_dependency(db, attribution, f"{customer360.urn}:customer-snapshot", maya)
        dataproducts.add_dependency(db, attribution, f"{orders.urn}:order-stream", maya)
        dataproducts.add_component(
            db, attribution, template_id="storage-delta-lake", actor=maya,
            values={
                "name": "attribution-store",
                "displayName": "Attribution Store",
                "description": "Touchpoint-level attribution results.",
                "catalog": "lakehouse",
                "dbSchema": "marketing",
                "table": "campaign_attribution",
                "partitionBy": ["event_date"],
                "zOrderBy": [],
                "retentionDays": 365,
            },
        )
        dataproducts.add_component(
            db, attribution, template_id="workload-airflow-dag", actor=maya,
            values={
                "name": "compute-attribution",
                "displayName": "Compute Attribution",
                "description": "Joins order events with customer segments and runs the attribution model.",
                "schedule": "0 2 * * *",
                "retries": 2,
                "slaMinutes": 120,
                "writesTo": "attribution-store",
                "readsFrom": [f"{customer360.urn}:customer-snapshot", f"{orders.urn}:order-stream"],
            },
        )
        dataproducts.add_component(
            db, attribution, template_id="outputport-snowflake-table", actor=maya,
            values={
                "name": "attribution-report",
                "displayName": "Attribution Report",
                "description": "Campaign level attributed revenue, refreshed daily.",
                "database": "ANALYTICS",
                "dbSchema": "MARKETING",
                "table": "CAMPAIGN_ATTRIBUTION",
                "warehouse": "WH_SMALL",
                "columns": _columns(
                    ("campaign_id", "string", "Identifier of the campaign.", False, False, "internal"),
                    ("channel", "string", "Acquisition channel.", False, False, "internal"),
                    ("attributed_revenue", "decimal", "Revenue attributed to the campaign, in EUR.", True, False, "confidential"),
                    ("conversions", "integer", "Number of attributed conversions.", True, False, "internal"),
                    ("event_date", "date", "Reporting day.", False, False, "internal"),
                ),
                "intervalOfChange": "1 day",
                "timeliness": "6 hours",
                "upTime": "99%",
                "termsAndConditions": "Figures are modelled, not accounted. Do not use for statutory reporting.",
            },
        )
        provisioning.deploy(db, attribution, environment="development", actor=maya)

        # ------------------------------------------------------------------
        # 4. finance / revenue-reporting — still a draft, deliberately failing
        #    a couple of policies so the governance view has something to show
        # ------------------------------------------------------------------
        revenue = dataproducts.scaffold(
            db,
            template_id="dataproduct-standard",
            values={
                "name": "revenue-reporting",
                "displayName": "Revenue Reporting",
                "domain": "finance",
                "description": "Statutory revenue figures.",
                "email": "finance-data@acme.io",
                "maturity": "strategic",
                "informationSLA": "48h",
                "tags": [],
            },
            owner=users["admin"],
        )
        dataproducts.add_component(
            db, revenue, template_id="storage-s3-bucket", actor=users["admin"],
            values={
                "name": "ledger-extracts",
                "displayName": "Ledger Extracts",
                "description": "Raw extracts from the general ledger.",
                "region": "eu-central-1",
                "format": "parquet",
                "retentionDays": 2555,
                "encryption": "aws:kms",
                "versioning": True,
            },
        )

        # ------------------------------------------------------------------
        # 5. logistics / delivery-promise — an ML feature product
        # ------------------------------------------------------------------
        delivery = dataproducts.scaffold(
            db,
            template_id="dataproduct-ml-feature",
            values={
                "name": "delivery-promise",
                "displayName": "Delivery Promise Features",
                "domain": "logistics",
                "description": (
                    "Features used by the delivery-date prediction model: historical transit "
                    "times, carrier reliability and warehouse load."
                ),
                "entity": "shipment",
                "refreshSchedule": "0 3 * * *",
                "email": "logistics-data@acme.io",
                "tags": ["ml", "features", "logistics"],
            },
            owner=users["admin"],
        )
        dataproducts.add_component(
            db, delivery, template_id="outputport-rest-api", actor=users["admin"],
            values={
                "name": "feature-lookup",
                "displayName": "Feature Lookup API",
                "description": "Online lookup of the latest features for a shipment.",
                "basePath": "/v1/shipments/features",
                "authMode": "oauth2",
                "rateLimit": 3000,
                "replicas": 3,
                "columns": _columns(
                    ("shipment_id", "string", "Identifier of the shipment.", False, False, "internal"),
                    ("carrier_reliability", "double", "Rolling 30-day on-time rate of the carrier.", True, False, "internal"),
                    ("median_transit_hours", "double", "Median transit time on this lane.", True, False, "internal"),
                    ("warehouse_load", "double", "Current load factor of the dispatching warehouse.", True, False, "internal"),
                ),
                "timeliness": "near real-time",
                "upTime": "99.9%",
                "termsAndConditions": "Intended for online inference; not a system of record.",
            },
        )
        dataproducts.add_component(
            db, delivery, template_id="observability-data-quality", actor=users["admin"],
            values={
                "name": "feature-quality",
                "displayName": "Feature Quality",
                "description": "Detects feature drift and stale features before the model sees them.",
                "monitors": "feature-lookup",
                "freshnessMinutes": 60,
                "minRowCount": 1000,
                "nullThresholdPercent": 2,
                "checkSchemaDrift": True,
                "channel": "#ml-alerts",
                "severity": "high",
            },
        )
        dataproducts.release(db, delivery, version="0.2.0", notes="Feature set for the first model.", actor=users["admin"])
        provisioning.deploy(db, delivery, environment="development", actor=users["admin"])
        provisioning.deploy(db, delivery, environment="production", actor=users["admin"])
        dataproducts.publish(db, delivery, users["admin"])

        # ------------------------------------------------------------------
        # access requests
        # ------------------------------------------------------------------
        snapshot_port = next(c for c in customer360.components if c.name == "customer-snapshot")
        stream_port = next(c for c in orders.components if c.name == "order-stream")

        approved = marketplace.request_access(
            db, dp=customer360, component=snapshot_port, requester=maya,
            purpose="Join customer segments onto attributed revenue in the marketing report.",
            consumer_dp_urn=attribution.urn,
        )
        marketplace.decide(db, approved, approve=True, decider=alice, note="Approved for the attribution use case.")

        marketplace.request_access(
            db, dp=orders, component=stream_port, requester=bruno,
            purpose="Prototype a near real-time revenue dashboard for the weekly finance review.",
        )
        marketplace.request_access(
            db, dp=customer360, component=snapshot_port, requester=bruno,
            purpose="Cross-check finance revenue figures against customer lifetime value.",
        )

        db.commit()
        print("seeded:")
        print(f"  users       : {', '.join(u[0] for u in USERS)} (password: {PASSWORD})")
        print(f"  domains     : {', '.join(d[0] for d in DOMAINS)}")
        print("  products    : customer-360, order-events, campaign-attribution, "
              "revenue-reporting, delivery-promise")
        client = github.get_client()
        if client is not None:
            print(f"  repositories: https://github.com/{client.owner} (prefix '{client.repo_prefix}')")
        else:
            print(f"  repositories: {settings.repos_dir} (local mode)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the DataMesh Platform with demo data")
    parser.add_argument("--reset", action="store_true", help="drop the database and all repositories first")
    parser.add_argument(
        "--local", action="store_true",
        help="keep the demo repositories local even when a GitHub token is configured",
    )
    args = parser.parse_args()
    if args.local:
        github.disable()

    client = github.get_client()
    if client is not None:
        print(
            f"GitHub mode is ON — seeding will create {len(DOMAINS) + 1} real repositories "
            f"under '{settings.github_owner or 'the token user'}' "
            f"(prefix '{settings.github_repo_prefix}'). Pass --local to keep the demo offline."
        )
    if args.reset:
        reset()
    seed()
    return 0


if __name__ == "__main__":
    sys.exit(main())
