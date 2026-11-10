-- SKN36 3rd project: PostgreSQL MVP storage (PR #25 + PR #26)
-- Non-destructive: no DROP TABLE, idempotent CREATE IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS welfare_policies (
    policy_id TEXT PRIMARY KEY,               -- PR26: local:<original servId>
    source_serv_id TEXT NOT NULL UNIQUE,       -- PR25: original API ID
    title TEXT NOT NULL,
    summary TEXT,
    target_text TEXT,
    selection_criteria_text TEXT,
    benefit_text TEXT,
    application_text TEXT,
    application_method_name TEXT,
    department TEXT,
    contact TEXT,
    sido_name TEXT,
    sigungu_name TEXT,
    region_code TEXT,
    region_scope TEXT,
    region_review_status TEXT,
    region_selection_verified BOOLEAN NOT NULL DEFAULT FALSE,
    elderly_category TEXT,
    elderly_eligibility_verified BOOLEAN NOT NULL DEFAULT FALSE,
    detail_fetched BOOLEAN NOT NULL DEFAULT FALSE,
    source_url TEXT,
    start_date DATE,
    end_date DATE,
    updated_at_source DATE,
    rag_text TEXT NOT NULL,
    metadata JSONB NOT NULL,
    preprocessed_raw JSONB NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS source_documents (
    document_id TEXT PRIMARY KEY,
    title TEXT,
    publisher TEXT,
    publication_year INTEGER,
    document_type TEXT,
    source_url TEXT,
    metadata JSONB NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS guideline_sections (
    section_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents(document_id),
    text_content TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    metadata JSONB NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT guideline_page_range CHECK (page_start IS NULL OR page_end IS NULL OR (page_start > 0 AND page_end >= page_start))
);
CREATE TABLE IF NOT EXISTS rag_chunks (
    id UUID PRIMARY KEY,                 -- PR26 id = uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)
    chunk_id TEXT NOT NULL UNIQUE,
    record_type TEXT NOT NULL CHECK (record_type IN ('policy','guideline')),
    parent_id TEXT NOT NULL,             -- policy_id or section_id
    chunk_strategy TEXT NOT NULL CHECK (chunk_strategy IN ('fixed','structure')),
    text_content TEXT NOT NULL,
    metadata JSONB NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_parent ON rag_chunks (record_type, parent_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_strategy ON rag_chunks (chunk_strategy);
CREATE INDEX IF NOT EXISTS idx_policies_region ON welfare_policies (sido_name, sigungu_name);
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    input_summary JSONB NOT NULL,
    result_summary JSONB NOT NULL
);
-- Facility API is not yet finalized; no facilities table created in this release.
