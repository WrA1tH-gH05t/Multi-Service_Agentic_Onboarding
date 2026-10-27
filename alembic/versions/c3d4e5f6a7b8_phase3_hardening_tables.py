"""add collection_sessions table, validation_rules table, idempotency_keys table,
enhance service_documents with alternatives, add documents unique constraint

Revision ID: c3d4e5f6a7b8
Revises: 35447892189e
Create Date: 2026-10-10

Phase 3: Hardening Collection Agent

NOTE: Tables may already exist from DatabaseService.connect() -> Base.metadata.create_all().
This migration is idempotent — uses raw SQL checks before creating.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c3d4e5f6a7b8'
down_revision = '35447892189e'
branch_labels = None
depends_on = None


def _table_exists(op_conn, table_name):
    """Check if a PostgreSQL table exists using raw string formatting."""
    result = op_conn.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = '{}'".format(table_name)
        )
    ).scalar()
    return bool(result)


def _column_exists(op_conn, table_name, column_name):
    """Check if a column exists."""
    result = op_conn.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.columns "
            "  WHERE table_schema = 'public' AND table_name = '{}' AND column_name = '{}'".format(table_name, column_name)
        )
    ).scalar()
    return bool(result)


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. collection_sessions table ──
    if not _table_exists(conn, 'collection_sessions'):
        op.create_table(
            'collection_sessions',
            sa.Column('session_id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=True, index=True),
            sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.application_id'), nullable=True, index=True),
            sa.Column('service_id', sa.String(100), nullable=False),
            sa.Column('service_name', sa.String(255), nullable=True),
            sa.Column('status', sa.String(20), server_default='collecting'),
            sa.Column('document_requirements', postgresql.JSON, nullable=True),
            sa.Column('submitted_file_ids', postgresql.JSON, nullable=True),
            sa.Column('conversation_history', postgresql.JSON, nullable=True),
            sa.Column('notes', postgresql.JSON, nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # ── 2. validation_rules table ──
    if not _table_exists(conn, 'validation_rules'):
        op.create_table(
            'validation_rules',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('service_id', sa.String(100), nullable=False, index=True),
            sa.Column('document_type', sa.String(50), nullable=False),
            sa.Column('mandatory_fields', postgresql.JSON, nullable=True),
            sa.Column('optional_fields', postgresql.JSON, nullable=True),
            sa.Column('field_rules', postgresql.JSON, nullable=True),
            sa.Column('extraction_threshold', sa.Float(), nullable=True, server_default='0.5'),
            sa.Column('human_review_threshold', sa.Float(), nullable=True, server_default='0.7'),
            sa.Column('reject_threshold', sa.Integer(), nullable=True, server_default='3'),
            sa.Column('source', sa.String(500), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Index('ix_validation_rules_service_doc', 'service_id', 'document_type'),
        )

    # ── 3. idempotency_keys table ──
    if not _table_exists(conn, 'idempotency_keys'):
        op.create_table(
            'idempotency_keys',
            sa.Column('idempotency_key', sa.String(64), primary_key=True),
            sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.application_id'), nullable=True, index=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=True, index=True),
            sa.Column('response_json', postgresql.JSON, nullable=True),
            sa.Column('response_status', sa.Integer(), nullable=True, server_default='200'),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # ── 4. Enhance documents table: add content_hash and unique constraint ──
    if _table_exists(conn, 'documents'):
        if not _column_exists(conn, 'documents', 'content_hash'):
            op.add_column('documents', sa.Column('content_hash', sa.String(64), nullable=True, index=True))

        has_constraint = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_documents_user_hash')"
            )
        ).scalar()
        if not has_constraint:
            op.create_unique_constraint(
                'uq_documents_user_hash',
                'documents',
                ['user_id', 'content_hash']
            )

    # ── 5. Enhance service_documents table: add allowed_alternatives ──
    if _table_exists(conn, 'service_documents'):
        if not _column_exists(conn, 'service_documents', 'allowed_alternatives'):
            op.add_column(
                'service_documents',
                sa.Column('allowed_alternatives', postgresql.JSON, nullable=True)
            )


def downgrade() -> None:
    conn = op.get_bind()

    # ── 5. Remove allowed_alternatives from service_documents ──
    if _table_exists(conn, 'service_documents') and _column_exists(conn, 'service_documents', 'allowed_alternatives'):
        op.drop_column('service_documents', 'allowed_alternatives')

    # ── 4. Remove content_hash and unique constraint from documents ──
    if _table_exists(conn, 'documents'):
        has_constraint = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_documents_user_hash')"
            )
        ).scalar()
        if has_constraint:
            op.drop_constraint('uq_documents_user_hash', 'documents', type_='unique')

        if _column_exists(conn, 'documents', 'content_hash'):
            op.drop_column('documents', 'content_hash')

    # ── 3. Remove idempotency_keys table ──
    if _table_exists(conn, 'idempotency_keys'):
        op.drop_table('idempotency_keys')

    # ── 2. Remove validation_rules table ──
    if _table_exists(conn, 'validation_rules'):
        op.drop_table('validation_rules')

    # ── 1. Remove collection_sessions table ──
    if _table_exists(conn, 'collection_sessions'):
        op.drop_table('collection_sessions')
