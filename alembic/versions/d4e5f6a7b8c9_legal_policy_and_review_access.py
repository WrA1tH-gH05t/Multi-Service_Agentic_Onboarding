"""add legal policy, terms acceptance, application consent, government agency routing, user roles and access audit tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-16

Docintake Legal Framework and Review Access Migration
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def _table_exists(op_conn, table_name):
    """Check if table exists in PostgreSQL or SQLite."""
    try:
        result = op_conn.execute(
            sa.text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                f" WHERE table_name = '{table_name}'"
                ");"
            )
        )
        return bool(result.scalar())
    except Exception:
        # SQLite fallback check
        res = op_conn.execute(
            sa.text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
        )
        return bool(res.scalar())


def upgrade() -> None:
    conn = op.get_bind()

    # 1. policy_documents table
    if not _table_exists(conn, 'policy_documents'):
        op.create_table(
            'policy_documents',
            sa.Column('policy_id', sa.String(50), primary_key=True),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('version', sa.String(20), nullable=False),
            sa.Column('status', sa.String(50), server_default='DRAFT — PENDING LEGAL APPROVAL'),
            sa.Column('effective_date', sa.String(50), server_default='Pending Approval'),
            sa.Column('content_hash', sa.String(64), nullable=False),
            sa.Column('pdf_filename', sa.String(255), nullable=False),
            sa.Column('content_markdown', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 2. user_terms_acceptances table
    if not _table_exists(conn, 'user_terms_acceptances'):
        op.create_table(
            'user_terms_acceptances',
            sa.Column('acceptance_id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=False, index=True),
            sa.Column('policy_id', sa.String(50), nullable=False),
            sa.Column('version', sa.String(20), nullable=False),
            sa.Column('content_hash', sa.String(64), nullable=False),
            sa.Column('accepted', sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column('accepted_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('ip_address', sa.String(50), nullable=True),
            sa.Column('user_agent', sa.String(255), nullable=True),
        )

    # 3. government_agencies table
    if not _table_exists(conn, 'government_agencies'):
        op.create_table(
            'government_agencies',
            sa.Column('agency_id', sa.String(50), primary_key=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('service_id', sa.String(100), nullable=False, index=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 4. user_roles table
    if not _table_exists(conn, 'user_roles'):
        op.create_table(
            'user_roles',
            sa.Column('role_id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=False, index=True),
            sa.Column('role_name', sa.String(50), nullable=False),
            sa.Column('agency_id', sa.String(50), sa.ForeignKey('government_agencies.agency_id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 5. application_consents table
    if not _table_exists(conn, 'application_consents'):
        op.create_table(
            'application_consents',
            sa.Column('consent_id', sa.String(36), primary_key=True),
            sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.application_id'), nullable=False, index=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=False, index=True),
            sa.Column('service_id', sa.String(100), nullable=False),
            sa.Column('designated_agency', sa.String(50), nullable=False),
            sa.Column('status', sa.String(30), nullable=False),
            sa.Column('consent_text_version', sa.String(20), server_default='1.0'),
            sa.Column('consent_text', sa.Text(), nullable=False),
            sa.Column('staged_documents_scope', sa.JSON(), nullable=True),
            sa.Column('agreed_at', sa.DateTime(), nullable=True),
            sa.Column('declined_at', sa.DateTime(), nullable=True),
            sa.Column('withdrawn_at', sa.DateTime(), nullable=True),
            sa.Column('withdrawal_reason', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 6. document_access_audits table
    if not _table_exists(conn, 'document_access_audits'):
        op.create_table(
            'document_access_audits',
            sa.Column('audit_id', sa.String(36), primary_key=True),
            sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.document_id'), nullable=True, index=True),
            sa.Column('application_id', sa.String(36), nullable=True, index=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=True, index=True),
            sa.Column('user_role', sa.String(50), nullable=False),
            sa.Column('agency_id', sa.String(50), nullable=True),
            sa.Column('action', sa.String(50), nullable=False),
            sa.Column('access_granted', sa.Boolean(), nullable=False),
            sa.Column('denial_reason', sa.String(255), nullable=True),
            sa.Column('ip_address', sa.String(50), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table('document_access_audits')
    op.drop_table('application_consents')
    op.drop_table('user_roles')
    op.drop_table('government_agencies')
    op.drop_table('user_terms_acceptances')
    op.drop_table('policy_documents')
