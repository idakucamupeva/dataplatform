"""The scaffolder: form validation and structured rendering."""

from __future__ import annotations

import pytest

from app.services.templates import TemplateError_, render_node, template_registry


def test_every_shipped_template_declares_what_it_produces():
    for template in template_registry.all():
        assert template.id and template.name
        assert template.type in ("dataproduct", "component")
        if template.type == "dataproduct":
            assert template.descriptor, f"{template.id} produces no descriptor"
        else:
            assert template.component, f"{template.id} produces no component"
            assert template.kind, f"{template.id} declares no component kind"


def test_a_raw_reference_keeps_the_value_typed():
    rendered = render_node({"partitions": "${count}", "name": "topic-{{ suffix }}"}, {"count": 12, "suffix": "v1"})
    assert rendered == {"partitions": 12, "name": "topic-v1"}


def test_empty_values_are_dropped_from_the_rendered_block():
    rendered = render_node({"keep": "yes", "drop": "{{ blank }}"}, {"blank": ""})
    assert rendered == {"keep": "yes"}


def test_required_fields_are_enforced():
    template = template_registry.get("outputport-snowflake-table")
    with pytest.raises(TemplateError_) as excinfo:
        template_registry.validate_values(template, {"name": "port"})
    assert "required" in str(excinfo.value)


def test_a_name_that_is_not_a_slug_is_rejected():
    template = template_registry.get("storage-s3-bucket")
    with pytest.raises(TemplateError_):
        template_registry.validate_values(
            template, {"name": "Not A Slug", "description": "x", "region": "eu-west-1"}
        )


def test_values_are_coerced_to_the_declared_types():
    template = template_registry.get("outputport-kafka-topic")
    values = template_registry.validate_values(
        template,
        {
            "name": "order-stream",
            "description": "Events.",
            "topic": "sales.orders.v1",
            "partitions": "6",
            "replication": "3",
            "retentionHours": "48",
            "columns": [{"name": "order_id", "dataType": "string"}],
            "tags": "orders, streaming",
        },
    )
    assert values["partitions"] == 6
    assert values["tags"] == ["orders", "streaming"]
    assert values["columns"][0]["classification"] == "internal"


def test_duplicate_schema_columns_are_rejected():
    template = template_registry.get("outputport-snowflake-table")
    with pytest.raises(TemplateError_) as excinfo:
        template_registry.validate_values(
            template,
            {
                "name": "port", "description": "x", "database": "DB", "dbSchema": "S", "table": "T",
                "columns": [{"name": "id"}, {"name": "id"}],
            },
        )
    assert "twice" in str(excinfo.value)


def test_rendering_a_component_produces_a_provisionable_block():
    template = template_registry.get("outputport-snowflake-table")
    values = template_registry.validate_values(
        template,
        {
            "name": "customer-snapshot", "description": "Snapshot.", "database": "ANALYTICS",
            "dbSchema": "SALES", "table": "CUSTOMER", "warehouse": "WH_SMALL",
            "columns": [{"name": "customer_id", "dataType": "string", "description": "Key."}],
            "intervalOfChange": "1 day", "timeliness": "2h", "upTime": "99%",
            "termsAndConditions": "Internal.", "tags": [],
        },
    )
    block = render_node(template.component, {**values, "__domain__": "sales", "__data_product__": "customer-360"})
    assert block["kind"] == "outputport"
    assert block["specific"]["table"] == "CUSTOMER"
    assert block["specific"]["grantRole"] == "ROLE_ANALYTICS_SALES_CUSTOMER_SNAPSHOT_READ"
    assert block["dataContract"]["schema"][0]["name"] == "customer_id"


def test_extra_repository_files_are_rendered():
    template = template_registry.get("workload-airflow-dag")
    values = template_registry.validate_values(
        template,
        {"name": "daily-load", "description": "Loads.", "schedule": "@hourly", "retries": 2,
         "slaMinutes": 60, "writesTo": "store", "readsFrom": []},
    )
    files = template_registry.render_files(
        template, {**values, "__domain__": "sales", "__data_product__": "orders", "__owner__": "alice"}
    )
    (path, body), = files.items()
    assert path == "components/daily-load/dag.py"
    assert "sales_orders_daily_load" in body
