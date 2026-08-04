"""Technology adapters.

Each one simulates the calls a real provisioner would make and returns the
identifiers of the resources it created, which the platform stores on the
deployment and shows in the UI.
"""

from __future__ import annotations

from app.provisioners.base import ProvisionResult, Provisioner, registry
from app.schemas.descriptor import Component, Descriptor


class SnowflakeProvisioner(Provisioner):
    technology = "snowflake"
    platform = "Snowflake"
    required_keys = ("database", "schema", "table")

    def provision(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        spec = component.specific
        database = self.qualify(environment, spec["database"]).upper()
        fqn = f"{database}.{spec['schema']}.{spec['table']}".upper()
        role = spec.get("grantRole", f"ROLE_{spec['table']}_READ").upper()
        columns = component.data_contract.schema_ if component.data_contract else []
        logs = [
            f"[snowflake] using warehouse {spec.get('warehouse', 'WH_SMALL')}",
            f"[snowflake] create database if not exists {database}",
            f"[snowflake] create schema if not exists {database}.{spec['schema']}",
            f"[snowflake] create or replace view {fqn} ({len(columns)} columns)",
            f"[snowflake] create role if not exists {role}",
            f"[snowflake] grant select on {fqn} to role {role}",
            "[snowflake] masking policies applied to "
            f"{sum(1 for c in columns if c.pii)} personal-data column(s)",
        ]
        return ProvisionResult(
            ok=True,
            logs=logs,
            outputs={
                "objectName": fqn,
                "readRole": role,
                "jdbcUrl": f"jdbc:snowflake://acme.snowflakecomputing.com/?db={database}&schema={spec['schema']}",
            },
        )

    def destroy(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        spec = component.specific
        database = self.qualify(environment, spec["database"]).upper()
        fqn = f"{database}.{spec['schema']}.{spec['table']}".upper()
        return ProvisionResult(ok=True, logs=[f"[snowflake] drop view if exists {fqn}"])


class KafkaProvisioner(Provisioner):
    technology = "kafka"
    platform = "Confluent"
    required_keys = ("topic",)

    def validate(self, component: Component, descriptor: Descriptor, environment: str) -> list[str]:
        errors = super().validate(component, descriptor, environment)
        partitions = component.specific.get("partitions", 1)
        replication = component.specific.get("replicationFactor", 1)
        if isinstance(partitions, int) and partitions < 1:
            errors.append("`specific.partitions` must be at least 1")
        if environment == "production" and isinstance(replication, int) and replication < 3:
            errors.append("production topics require a replication factor of at least 3")
        return errors

    def provision(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        spec = component.specific
        topic = f"{self.env_prefix(environment)}.{spec['topic']}"
        subject = f"{topic}-value"
        return ProvisionResult(
            ok=True,
            logs=[
                f"[kafka] create topic {topic} "
                f"(partitions={spec.get('partitions', 1)}, rf={spec.get('replicationFactor', 1)})",
                f"[kafka] set retention.ms={int(spec.get('retentionHours', 168)) * 3_600_000}, "
                f"cleanup.policy={spec.get('cleanupPolicy', 'delete')}",
                f"[schema-registry] register {subject} (AVRO, compatibility=BACKWARD)",
                f"[kafka] create ACLs for consumer group prefix {spec.get('consumerGroupPrefix', topic)}",
            ],
            outputs={
                "topic": topic,
                "bootstrapServers": f"broker-{self.env_prefix(environment)}.acme.internal:9092",
                "schemaSubject": subject,
            },
        )


class S3Provisioner(Provisioner):
    technology = "s3"
    platform = "AWS"
    required_keys = ("bucket", "region")

    def provision(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        spec = component.specific
        bucket = f"{spec['bucket']}-{self.env_prefix(environment)}"
        logs = [
            f"[aws] create bucket s3://{bucket} in {spec['region']}",
            f"[aws] default encryption {spec.get('encryption', 'AES256')}",
            f"[aws] lifecycle rule: expire after {spec.get('retentionDays', 365)} days",
        ]
        if spec.get("versioning"):
            logs.append("[aws] enable object versioning")
        logs.append(f"[aws] attach IAM policy {bucket}-rw to the data product role")
        return ProvisionResult(
            ok=True,
            logs=logs,
            outputs={"bucket": bucket, "uri": f"s3://{bucket}/{spec.get('prefix', '')}", "region": spec["region"]},
        )


class DeltaProvisioner(Provisioner):
    technology = "delta-lake"
    platform = "Databricks"
    required_keys = ("catalog", "schema", "table")

    def provision(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        spec = component.specific
        catalog = self.qualify(environment, spec["catalog"])
        fqn = f"{catalog}.{spec['schema']}.{spec['table']}"
        logs = [
            f"[databricks] create catalog if not exists {catalog}",
            f"[databricks] create table {fqn} using delta",
        ]
        if spec.get("partitionBy"):
            logs.append(f"[databricks] partitioned by ({', '.join(spec['partitionBy'])})")
        if spec.get("zOrderBy"):
            logs.append(f"[databricks] optimize {fqn} zorder by ({', '.join(spec['zOrderBy'])})")
        logs.append(f"[unity-catalog] owner set to {descriptor.metadata.owner}")
        return ProvisionResult(
            ok=True,
            logs=logs,
            outputs={"table": fqn, "warehouseId": f"wh-{self.env_prefix(environment)}-01"},
        )


class AirflowProvisioner(Provisioner):
    technology = "airflow"
    platform = "Astronomer"
    required_keys = ("dagId", "schedule")

    def provision(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        spec = component.specific
        dag_id = self.qualify(environment, spec["dagId"])
        return ProvisionResult(
            ok=True,
            logs=[
                f"[airflow] sync components/{component.name}/dag.py to the {environment} deployment",
                f"[airflow] register DAG {dag_id} (schedule={spec['schedule']}, "
                f"retries={spec.get('retries', 0)})",
                f"[airflow] SLA miss callback -> {descriptor.metadata.email}",
                f"[airflow] unpause DAG {dag_id}" if environment != "development" else
                "[airflow] DAG left paused in development",
            ],
            outputs={
                "dagId": dag_id,
                "uiUrl": f"https://airflow-{self.env_prefix(environment)}.acme.io/dags/{dag_id}",
            },
        )


class DbtProvisioner(Provisioner):
    technology = "dbt"
    platform = "dbt Cloud"
    required_keys = ("project", "model", "targetSchema")

    def provision(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        spec = component.specific
        job = f"{spec['project']}-{spec['model']}-{self.env_prefix(environment)}"
        logs = [
            f"[dbt] resolve sources: {', '.join(spec.get('sources') or ['—'])}",
            f"[dbt] dbt build --select {spec['model']} --target {self.env_prefix(environment)}",
            f"[dbt] materialized as {spec.get('materialization', 'table')} in {spec['targetSchema']}",
        ]
        if spec.get("testsEnabled"):
            logs.append("[dbt] dbt test — 4 tests passed")
        logs.append(f"[dbt] create job {job} (schedule={spec.get('schedule', 'manual')})")
        return ProvisionResult(ok=True, logs=logs, outputs={"jobName": job, "docsUrl": f"https://dbt.acme.io/#!/model/{spec['model']}"})


class RestProvisioner(Provisioner):
    technology = "rest"
    platform = "Kubernetes"
    required_keys = ("basePath",)

    def provision(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        spec = component.specific
        host = f"api-{self.env_prefix(environment)}.acme.io"
        namespace = f"{descriptor.metadata.domain}-{descriptor.metadata.name}"
        return ProvisionResult(
            ok=True,
            logs=[
                f"[k8s] namespace {namespace} ensured",
                f"[k8s] deploy {component.name} (replicas={spec.get('replicas', 1)})",
                f"[gateway] route https://{host}{spec['basePath']} -> {component.name}.{namespace}",
                f"[gateway] auth={spec.get('authMode', 'oauth2')}, "
                f"rate limit={spec.get('rateLimitPerMinute', 60)}/min",
            ],
            outputs={"url": f"https://{host}{spec['basePath']}", "namespace": namespace},
        )


class ObservabilityProvisioner(Provisioner):
    technology = "great-expectations"
    platform = "Observability Platform"
    required_keys = ("monitors",)

    def validate(self, component: Component, descriptor: Descriptor, environment: str) -> list[str]:
        errors = super().validate(component, descriptor, environment)
        target = component.specific.get("monitors")
        if target and descriptor.component(target) is None:
            errors.append(f"`specific.monitors` points at '{target}', which is not a component of this product")
        return errors

    def provision(self, component: Component, descriptor: Descriptor, environment: str) -> ProvisionResult:
        spec = component.specific
        checks = spec.get("checks", {})
        suite = f"{descriptor.metadata.name}-{component.name}-{self.env_prefix(environment)}"
        logs = [
            f"[observability] create expectation suite {suite}",
            f"[observability] freshness <= {checks.get('freshnessMinutes', 60)} min",
            f"[observability] row count >= {checks.get('minRowCount', 1)}",
            f"[observability] null rate <= {checks.get('nullThresholdPercent', 0)}%",
        ]
        if checks.get("schemaDrift"):
            logs.append("[observability] schema drift checked against the published data contract")
        alerting = spec.get("alerting", {})
        logs.append(
            f"[observability] alerts -> {alerting.get('channel', '#data-alerts')} "
            f"(severity {alerting.get('severity', 'medium')})"
        )
        return ProvisionResult(ok=True, logs=logs, outputs={"suite": suite, "dashboard": f"https://observe.acme.io/{suite}"})


for _provisioner in (
    SnowflakeProvisioner(),
    KafkaProvisioner(),
    S3Provisioner(),
    DeltaProvisioner(),
    AirflowProvisioner(),
    DbtProvisioner(),
    RestProvisioner(),
    ObservabilityProvisioner(),
):
    registry.register(_provisioner)
