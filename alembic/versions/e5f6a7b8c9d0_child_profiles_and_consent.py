"""add child profiles, guardian consent, policy acceptance, and review consent tables

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-18

Docintake Parent/Guardian Accounts, Child Dependent Profiles & Consent Management
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
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
        res = op_conn.execute(
            sa.text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
        )
        return bool(res.scalar())


def upgrade() -> None:
    conn = op.get_bind()

    # 1. child_profiles table
    if not _table_exists(conn, 'child_profiles'):
        op.create_table(
            'child_profiles',
            sa.Column('profile_id', sa.String(36), primary_key=True),
            sa.Column('parent_user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=False, index=True),
            sa.Column('full_name', sa.String(255), nullable=False),
            sa.Column('date_of_birth', sa.String(20), nullable=False),
            sa.Column('relationship_type', sa.String(100), nullable=False),
            sa.Column('nationality', sa.String(100), nullable=True),
            sa.Column('guardian_authority_status', sa.String(50), server_default='pending'),
            sa.Column('guardian_verification_reference', sa.String(255), nullable=True),
            sa.Column('age_band', sa.String(20), nullable=True),
            sa.Column('profile_status', sa.String(50), server_default='active'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 2. guardian_consents table
    if not _table_exists(conn, 'guardian_consents'):
        op.create_table(
            'guardian_consents',
            sa.Column('consent_id', sa.String(36), primary_key=True),
            sa.Column('guardian_user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=False, index=True),
            sa.Column('child_profile_id', sa.String(36), sa.ForeignKey('child_profiles.profile_id'), nullable=False, index=True),
            sa.Column('consent_purpose', sa.String(255), nullable=False),
            sa.Column('privacy_policy_version', sa.String(50), server_default='v1.1'),
            sa.Column('consent_version', sa.String(50), server_default='v1.1'),
            sa.Column('verification_method', sa.String(100), nullable=True),
            sa.Column('consent_text_hash', sa.String(64), nullable=True),
            sa.Column('accepted_at', sa.DateTime(), nullable=True),
            sa.Column('withdrawn_at', sa.DateTime(), nullable=True),
            sa.Column('consent_status', sa.String(50), server_default='pending'),
            sa.Column('ip_address', sa.String(45), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 3. policy_acceptances table
    if not _table_exists(conn, 'policy_acceptances'):
        op.create_table(
            'policy_acceptances',
            sa.Column('acceptance_id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=False, index=True),
            sa.Column('policy_type', sa.String(100), nullable=False),
            sa.Column('policy_version', sa.String(50), nullable=False),
            sa.Column('policy_hash', sa.String(64), nullable=True),
            sa.Column('accepted_at', sa.DateTime(), nullable=True),
            sa.Column('acceptance_status', sa.String(50), server_default='accepted'),
            sa.Column('ip_address', sa.String(45), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 4. child_application_review_consents table
    if not _table_exists(conn, 'child_application_review_consents'):
        op.create_table(
            'child_application_review_consents',
            sa.Column('consent_id', sa.String(36), primary_key=True),
            sa.Column('guardian_user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=False, index=True),
            sa.Column('child_profile_id', sa.String(36), sa.ForeignKey('child_profiles.profile_id'), nullable=True, index=True),
            sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.application_id'), nullable=False, index=True),
            sa.Column('service_id', sa.String(100), nullable=False),
            sa.Column('receiving_agency_id', sa.String(100), nullable=True),
            sa.Column('policy_version', sa.String(50), server_default='v1.1'),
            sa.Column('consent_text_version', sa.String(50), server_default='v1.1'),
            sa.Column('consent_text_hash', sa.String(64), nullable=True),
            sa.Column('accepted_at', sa.DateTime(), nullable=True),
            sa.Column('declined_at', sa.DateTime(), nullable=True),
            sa.Column('withdrawn_at', sa.DateTime(), nullable=True),
            sa.Column('consent_status', sa.String(50), server_default='pending'),
            sa.Column('ip_address', sa.String(45), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # 5. child_audit_events table
    if not _table_exists(conn, 'child_audit_events'):
        op.create_table(
            'child_audit_events',
            sa.Column('event_id', sa.String(36), primary_key=True),
            sa.Column('event_type', sa.String(100), nullable=False, index=True),
            sa.Column('actor_user_id', sa.String(36), sa.ForeignKey('users.user_id'), nullable=True, index=True),
            sa.Column('child_profile_id', sa.String(36), nullable=True, index=True),
            sa.Column('application_id', sa.String(36), nullable=True, index=True),
            sa.Column('event_data', sa.JSON(), nullable=True),
            sa.Column('ip_address', sa.String(45), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), index=True),
        )


def downgrade() -> None:
    op.drop_table('child_audit_events')
    op.drop_table('child_application_review_consents')
    op.drop_table('policy_acceptances')
    op.drop_table('guardian_consents')
    op.drop_table('child_profiles')
