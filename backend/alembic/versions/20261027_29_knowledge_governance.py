"""Knowledge governance metadata. DRAFT: no real database migration authorized."""
import sqlalchemy as sa
from alembic import op

revision = "20261027_29"
down_revision = "20261015_28"
branch_labels = depends_on = None

TABLES = ['rag_knowledge_bases', 'rag_documents', 'rag_document_versions', 'rag_jobs', 'rag_index_versions', 'rag_chunks', 'rag_evaluation_runs']

def upgrade():
    op.create_table('rag_knowledge_bases',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('business_scope', sa.String(length=300), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('visibility', sa.String(length=20), nullable=False),
        sa.Column('read_roles', sa.JSON(), nullable=False),
        sa.Column('active_index_id', sa.Integer(), nullable=True),
        sa.Column('running_job_id', sa.Integer(), nullable=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('name', name=None),
        sa.CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name='ck_rag_base_status'),
        sa.CheckConstraint("visibility IN ('PUBLIC','ROLES','ADMIN')", name='ck_rag_base_visibility'),
    )
    op.create_table('rag_documents',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('base_id', sa.Integer(), sa.ForeignKey('rag_knowledge_bases.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('key', sa.String(length=180), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('current_version_id', sa.Integer(), nullable=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('deleted', sa.Boolean(), nullable=False),
        sa.Column('visibility', sa.String(length=20), nullable=False),
        sa.Column('read_roles', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('base_id', 'key', name='uq_rag_document_key'),
    )
    op.create_index('ix_rag_documents_base_id', 'rag_documents', ['base_id'], unique=False)
    op.create_table('rag_document_versions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('rag_documents.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('storage_key', sa.String(length=160), nullable=False),
        sa.Column('original_name', sa.String(length=180), nullable=False),
        sa.Column('source_label', sa.String(length=300), nullable=False),
        sa.Column('stage', sa.String(length=24), nullable=False),
        sa.Column('error_type', sa.String(length=80), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('document_id', 'version', name='uq_rag_document_version'),
    )
    op.create_index('ix_rag_document_versions_document_id', 'rag_document_versions', ['document_id'], unique=False)
    op.create_table('rag_jobs',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('base_id', sa.Integer(), sa.ForeignKey('rag_knowledge_bases.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('request_sha256', sa.String(length=64), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('stage', sa.String(length=24), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('lease_token', sa.String(length=32), nullable=True),
        sa.Column('lease_until', sa.DateTime(), nullable=True),
        sa.Column('retryable', sa.Boolean(), nullable=False),
        sa.Column('error_type', sa.String(length=80), nullable=True),
        sa.Column('result_index_id', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Double(), nullable=True),
        sa.Column('model_calls', sa.Integer(), nullable=True),
        sa.Column('cost', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('attempts >= 0 AND max_attempts BETWEEN 1 AND 3', name='ck_rag_job_attempts'),
        sa.UniqueConstraint('base_id', 'idempotency_key', name='uq_rag_job_key'),
    )
    op.create_index('ix_rag_jobs_base_id', 'rag_jobs', ['base_id'], unique=False)
    op.create_table('rag_index_versions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('base_id', sa.Integer(), sa.ForeignKey('rag_knowledge_bases.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('rag_jobs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('manifest_key', sa.String(length=200), nullable=False),
        sa.Column('manifest_sha256', sa.String(length=64), nullable=False),
        sa.Column('embedding_model', sa.String(length=120), nullable=False),
        sa.Column('model_revision', sa.String(length=100), nullable=False),
        sa.Column('dimension', sa.Integer(), nullable=False),
        sa.Column('configuration', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('validation_kind', sa.String(length=40), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('version', name=None),
        sa.UniqueConstraint('job_id', name=None),
    )
    op.create_index('ix_rag_index_versions_base_id', 'rag_index_versions', ['base_id'], unique=False)
    op.create_table('rag_chunks',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('index_id', sa.Integer(), sa.ForeignKey('rag_index_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('document_version_id', sa.Integer(), sa.ForeignKey('rag_document_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('chunk_id', sa.String(length=64), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
        sa.UniqueConstraint('index_id', 'chunk_id', name='uq_rag_chunk_identity'),
    )
    op.create_index('ix_rag_chunks_index_id', 'rag_chunks', ['index_id'], unique=False)
    op.create_table('rag_evaluation_runs',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('index_id', sa.Integer(), sa.ForeignKey('rag_index_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('dataset', sa.String(length=100), nullable=False),
        sa.Column('dataset_sha256', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('metrics', sa.JSON(), nullable=False),
        sa.Column('cases', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_rag_evaluation_runs_index_id', 'rag_evaluation_runs', ['index_id'], unique=False)

def downgrade():
    bind = op.get_bind()
    for name in TABLES:
        if bind.execute(sa.text("SELECT COUNT(*) FROM " + name)).scalar():
            raise RuntimeError("Refuse downgrade: knowledge governance contains data")
    for name in reversed(TABLES):
        op.drop_table(name)
