-- Boxen v1 reference schema.
-- Normative for table/column/constraint intent; migration files own deployed evolution.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;

BEGIN IMMEDIATE;

CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY,
    checksum_sha256 TEXT NOT NULL CHECK (length(checksum_sha256) = 64),
    applied_at TEXT NOT NULL
) STRICT;

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL CHECK (json_valid(value_json)),
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    password_hash TEXT NOT NULL,
    credential_version INTEGER NOT NULL DEFAULT 1 CHECK (credential_version >= 1),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    disabled_at TEXT
) STRICT;

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY CHECK (length(token_hash) = 64),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_version INTEGER NOT NULL,
    csrf_secret_hash TEXT NOT NULL CHECK (length(csrf_secret_hash) = 64),
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    client_fingerprint_hash TEXT,
    revoked_at TEXT
) STRICT;

CREATE INDEX ix_sessions_user_active ON sessions(user_id, expires_at) WHERE revoked_at IS NULL;

CREATE TABLE idempotency_records (
    actor_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    route_key TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL CHECK (length(request_sha256) = 64),
    response_status INTEGER NOT NULL CHECK (response_status BETWEEN 200 AND 599),
    response_headers_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(response_headers_json)),
    response_body_json TEXT CHECK (response_body_json IS NULL OR json_valid(response_body_json)),
    resource_location TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (actor_user_id, route_key, idempotency_key)
) STRICT;

CREATE INDEX ix_idempotency_expiry ON idempotency_records(expires_at);

CREATE TABLE boxes (
    id TEXT PRIMARY KEY,
    public_code TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    description_markdown TEXT NOT NULL DEFAULT '',
    description_html TEXT NOT NULL DEFAULT '',
    description_text TEXT NOT NULL DEFAULT '',
    markdown_renderer_version TEXT NOT NULL,
    lifecycle TEXT NOT NULL DEFAULT 'active' CHECK (lifecycle IN ('active', 'archived')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_by TEXT NOT NULL REFERENCES users(id),
    updated_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    CHECK (
        (lifecycle = 'active' AND archived_at IS NULL) OR
        (lifecycle = 'archived' AND archived_at IS NOT NULL)
    )
) STRICT;

CREATE INDEX ix_boxes_lifecycle_updated ON boxes(lifecycle, updated_at DESC);

CREATE TABLE box_code_tombstones (
    public_code TEXT PRIMARY KEY COLLATE NOCASE,
    purged_at TEXT NOT NULL,
    audit_sequence INTEGER
) STRICT;

CREATE TABLE box_images (
    id TEXT PRIMARY KEY,
    box_id TEXT NOT NULL REFERENCES boxes(id) ON DELETE CASCADE,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('staged', 'ready', 'rejected', 'deleted')),
    original_storage_key TEXT,
    display_storage_key TEXT,
    thumbnail_storage_key TEXT,
    original_filename TEXT NOT NULL,
    sha256 TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
    media_type TEXT,
    byte_size INTEGER CHECK (byte_size IS NULL OR byte_size > 0),
    width INTEGER CHECK (width IS NULL OR width > 0),
    height INTEGER CHECK (height IS NULL OR height > 0),
    derivative_renderer_version TEXT,
    caption TEXT NOT NULL DEFAULT '' CHECK (length(caption) <= 500),
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    CHECK (
        lifecycle <> 'ready' OR
        (original_storage_key IS NOT NULL AND display_storage_key IS NOT NULL AND
         thumbnail_storage_key IS NOT NULL AND sha256 IS NOT NULL AND
         media_type IN ('image/jpeg', 'image/png', 'image/webp') AND
         byte_size IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL)
    ),
    CHECK ((lifecycle = 'deleted') = (deleted_at IS NOT NULL))
) STRICT;

CREATE UNIQUE INDEX ux_box_images_order
    ON box_images(box_id, sort_order)
    WHERE lifecycle = 'ready';
CREATE UNIQUE INDEX ux_box_images_active_hash
    ON box_images(box_id, sha256)
    WHERE lifecycle = 'ready';
CREATE INDEX ix_box_images_box_lifecycle ON box_images(box_id, lifecycle);

CREATE TABLE inventory_items (
    id TEXT PRIMARY KEY,
    box_id TEXT NOT NULL REFERENCES boxes(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 160),
    normalized_name TEXT NOT NULL CHECK (length(normalized_name) BETWEEN 1 AND 200),
    quantity_milli INTEGER CHECK (quantity_milli IS NULL OR quantity_milli BETWEEN 1 AND 999999999),
    unit TEXT CHECK (unit IS NULL OR length(unit) BETWEEN 1 AND 24),
    notes_markdown TEXT NOT NULL DEFAULT '',
    notes_html TEXT NOT NULL DEFAULT '',
    notes_text TEXT NOT NULL DEFAULT '',
    markdown_renderer_version TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance IN ('manual', 'ai', 'mixed')),
    lifecycle TEXT NOT NULL DEFAULT 'active' CHECK (lifecycle IN ('active', 'removed')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_by TEXT NOT NULL REFERENCES users(id),
    updated_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    removed_at TEXT,
    CHECK ((lifecycle = 'removed') = (removed_at IS NOT NULL))
) STRICT;

CREATE INDEX ix_inventory_box_lifecycle ON inventory_items(box_id, lifecycle, normalized_name);

CREATE TABLE analysis_jobs (
    id TEXT PRIMARY KEY,
    image_id TEXT NOT NULL REFERENCES box_images(id) ON DELETE CASCADE,
    operation_key TEXT NOT NULL UNIQUE,
    idempotency_key TEXT,
    model_profile TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    output_schema_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    lease_token TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    error_code TEXT,
    error_summary TEXT CHECK (error_summary IS NULL OR length(error_summary) <= 1000),
    requested_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    CHECK (attempt_count <= max_attempts),
    CHECK (
        (state = 'running' AND lease_token IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR
        (state <> 'running' AND lease_token IS NULL AND lease_owner IS NULL AND lease_expires_at IS NULL)
    ),
    CHECK ((state IN ('succeeded', 'failed', 'cancelled')) = (completed_at IS NOT NULL))
) STRICT;

CREATE INDEX ix_analysis_jobs_claim ON analysis_jobs(state, created_at) WHERE state = 'queued';
CREATE INDEX ix_analysis_jobs_lease ON analysis_jobs(lease_expires_at) WHERE state = 'running';

CREATE TABLE ai_runs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    image_id TEXT NOT NULL REFERENCES box_images(id) ON DELETE CASCADE,
    image_sha256 TEXT NOT NULL CHECK (length(image_sha256) = 64),
    model_id TEXT NOT NULL,
    model_sha256 TEXT NOT NULL CHECK (length(model_sha256) = 64),
    projector_sha256 TEXT CHECK (projector_sha256 IS NULL OR length(projector_sha256) = 64),
    runtime_id TEXT NOT NULL,
    runtime_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    output_schema_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'cancelled')),
    raw_output_json TEXT CHECK (raw_output_json IS NULL OR json_valid(raw_output_json)),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    peak_memory_bytes INTEGER CHECK (peak_memory_bytes IS NULL OR peak_memory_bytes >= 0),
    error_code TEXT,
    error_summary TEXT CHECK (error_summary IS NULL OR length(error_summary) <= 1000),
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    CHECK ((status = 'succeeded') = (raw_output_json IS NOT NULL)),
    UNIQUE (job_id, attempt_number)
) STRICT;

CREATE TABLE item_observations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
    box_id TEXT NOT NULL REFERENCES boxes(id) ON DELETE CASCADE,
    image_id TEXT NOT NULL REFERENCES box_images(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    proposed_name TEXT NOT NULL CHECK (length(proposed_name) BETWEEN 1 AND 160),
    normalized_name TEXT NOT NULL,
    proposed_quantity_milli INTEGER CHECK (proposed_quantity_milli IS NULL OR proposed_quantity_milli BETWEEN 1 AND 999999999),
    proposed_unit TEXT CHECK (proposed_unit IS NULL OR length(proposed_unit) BETWEEN 1 AND 24),
    confidence_ppm INTEGER CHECK (confidence_ppm IS NULL OR confidence_ppm BETWEEN 0 AND 1000000),
    bounding_box_json TEXT CHECK (bounding_box_json IS NULL OR json_valid(bounding_box_json)),
    attributes_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(attributes_json)),
    decision TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending', 'accepted', 'rejected', 'superseded')),
    accepted_item_id TEXT REFERENCES inventory_items(id),
    decided_by TEXT REFERENCES users(id),
    decided_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, ordinal),
    CHECK (
        (decision = 'pending' AND accepted_item_id IS NULL AND decided_by IS NULL AND decided_at IS NULL) OR
        (decision = 'accepted' AND accepted_item_id IS NOT NULL AND decided_by IS NOT NULL AND decided_at IS NOT NULL) OR
        (decision = 'rejected' AND accepted_item_id IS NULL AND decided_by IS NOT NULL AND decided_at IS NOT NULL) OR
        (decision = 'superseded' AND accepted_item_id IS NULL AND decided_at IS NOT NULL)
    )
) STRICT;

CREATE INDEX ix_observations_box_decision ON item_observations(box_id, decision, created_at);
CREATE INDEX ix_observations_item ON item_observations(accepted_item_id) WHERE accepted_item_id IS NOT NULL;

CREATE TABLE label_profiles (
    key TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK (version >= 1),
    display_name TEXT NOT NULL,
    width_micrometers INTEGER NOT NULL CHECK (width_micrometers > 0),
    height_micrometers INTEGER NOT NULL CHECK (height_micrometers > 0),
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE audit_log (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_public_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE INDEX ix_audit_target ON audit_log(target_type, target_public_id, sequence DESC);
CREATE INDEX ix_audit_actor ON audit_log(actor_user_id, sequence DESC);

CREATE TRIGGER audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER ai_runs_no_update
BEFORE UPDATE ON ai_runs
BEGIN
    SELECT RAISE(ABORT, 'ai_runs are immutable');
END;


CREATE TABLE maintenance_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('search_verify', 'search_rebuild', 'media_verify', 'derivative_rebuild')),
    operation_key TEXT NOT NULL UNIQUE,
    idempotency_key TEXT,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    progress_current INTEGER CHECK (progress_current IS NULL OR progress_current >= 0),
    progress_total INTEGER CHECK (progress_total IS NULL OR progress_total >= 0),
    result_json TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
    lease_token TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    error_code TEXT,
    error_summary TEXT CHECK (error_summary IS NULL OR length(error_summary) <= 1000),
    requested_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    CHECK (
        (state = 'running' AND lease_token IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR
        (state <> 'running' AND lease_token IS NULL AND lease_owner IS NULL AND lease_expires_at IS NULL)
    ),
    CHECK ((state IN ('succeeded', 'failed', 'cancelled')) = (completed_at IS NOT NULL)),
    CHECK (progress_total IS NULL OR progress_current IS NULL OR progress_current <= progress_total)
) STRICT;

CREATE INDEX ix_maintenance_jobs_claim ON maintenance_jobs(state, created_at) WHERE state = 'queued';

CREATE TABLE backups (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('creating', 'verifying', 'verified', 'failed', 'deleted')),
    relative_path TEXT NOT NULL UNIQUE,
    format_version INTEGER NOT NULL CHECK (format_version >= 1),
    schema_version TEXT NOT NULL,
    manifest_sha256 TEXT CHECK (manifest_sha256 IS NULL OR length(manifest_sha256) = 64),
    database_sha256 TEXT CHECK (database_sha256 IS NULL OR length(database_sha256) = 64),
    file_count INTEGER CHECK (file_count IS NULL OR file_count >= 0),
    total_bytes INTEGER CHECK (total_bytes IS NULL OR total_bytes >= 0),
    error_code TEXT,
    error_summary TEXT CHECK (error_summary IS NULL OR length(error_summary) <= 1000),
    requested_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    verified_at TEXT,
    deleted_at TEXT
) STRICT;

CREATE VIRTUAL TABLE box_search USING fts5(
    box_id UNINDEXED,
    code,
    name,
    description,
    item_names,
    item_notes,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE search_projection_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    projection_version TEXT NOT NULL,
    last_rebuilt_at TEXT,
    last_verified_at TEXT,
    source_row_count INTEGER NOT NULL DEFAULT 0 CHECK (source_row_count >= 0),
    projection_row_count INTEGER NOT NULL DEFAULT 0 CHECK (projection_row_count >= 0),
    state TEXT NOT NULL CHECK (state IN ('ready', 'rebuilding', 'invalid'))
) STRICT;

INSERT INTO search_projection_state (
    singleton, projection_version, source_row_count, projection_row_count, state
) VALUES (1, 'box-search-v1', 0, 0, 'ready');

COMMIT;
