"""Create the initial PulseHunter persistence schema.

Revision ID: 20260917_0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260917_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("device_type", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "online",
                "offline",
                "busy",
                name="device_status",
                native_enum=False,
                length=16,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("endpoint_url", sa.String(length=512), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.UniqueConstraint("name", name=op.f("uq_devices_name")),
    )
    op.create_index(op.f("ix_devices_status"), "devices", ["status"])
    op.create_index(op.f("ix_devices_last_heartbeat_at"), "devices", ["last_heartbeat_at"])

    op.create_table(
        "test_suites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_suites")),
        sa.UniqueConstraint("slug", name=op.f("uq_test_suites_slug")),
    )

    op.create_table(
        "test_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_suite_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "passed",
                "failed",
                "cancelled",
                name="run_status",
                native_enum=False,
                length=16,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["test_suite_id"],
            ["test_suites.id"],
            name=op.f("fk_test_runs_test_suite_id_test_suites"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_runs")),
    )
    op.create_index(op.f("ix_test_runs_test_suite_id"), "test_runs", ["test_suite_id"])
    op.create_index(op.f("ix_test_runs_status"), "test_runs", ["status"])

    op.create_table(
        "test_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "retrying",
                "passed",
                "failed",
                "timed_out",
                name="job_status",
                native_enum=False,
                length=16,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("logs", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_duration", sa.Float(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_task_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_test_jobs_device_id_devices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["test_run_id"],
            ["test_runs.id"],
            name=op.f("fk_test_jobs_test_run_id_test_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_jobs")),
        sa.UniqueConstraint("test_run_id", "device_id", name="uq_test_jobs_run_device"),
    )
    op.create_index(op.f("ix_test_jobs_device_id"), "test_jobs", ["device_id"])
    op.create_index(op.f("ix_test_jobs_status"), "test_jobs", ["status"])
    op.create_index(op.f("ix_test_jobs_test_run_id"), "test_jobs", ["test_run_id"])
    op.create_index(op.f("ix_test_jobs_next_attempt_at"), "test_jobs", ["next_attempt_at"])
    op.create_index(op.f("ix_test_jobs_lease_expires_at"), "test_jobs", ["lease_expires_at"])
    op.create_index("ix_test_jobs_dispatchable", "test_jobs", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_test_jobs_dispatchable", table_name="test_jobs")
    op.drop_index(op.f("ix_test_jobs_lease_expires_at"), table_name="test_jobs")
    op.drop_index(op.f("ix_test_jobs_next_attempt_at"), table_name="test_jobs")
    op.drop_index(op.f("ix_test_jobs_test_run_id"), table_name="test_jobs")
    op.drop_index(op.f("ix_test_jobs_status"), table_name="test_jobs")
    op.drop_index(op.f("ix_test_jobs_device_id"), table_name="test_jobs")
    op.drop_table("test_jobs")
    op.drop_index(op.f("ix_test_runs_status"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_test_suite_id"), table_name="test_runs")
    op.drop_table("test_runs")
    op.drop_table("test_suites")
    op.drop_index(op.f("ix_devices_last_heartbeat_at"), table_name="devices")
    op.drop_index(op.f("ix_devices_status"), table_name="devices")
    op.drop_table("devices")
