-- Local recovery identity, administrator session inventory, and OIDC identity/state store.
ALTER TABLE users ADD COLUMN is_system_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_system_admin IN (0, 1));

UPDATE users SET is_system_admin = 1 WHERE id = (
    SELECT id FROM users
    WHERE role = 'owner' AND status = 'active' AND password_hash LIKE '$argon2%'
    ORDER BY created_at, id LIMIT 1
);

CREATE UNIQUE INDEX ix_users_system_admin ON users(is_system_admin) WHERE is_system_admin = 1;

CREATE TRIGGER protect_system_admin_update BEFORE UPDATE ON users
WHEN OLD.is_system_admin = 1 AND (
    NEW.is_system_admin != 1 OR NEW.role != 'owner' OR NEW.status != 'active'
    OR NEW.password_hash LIKE '!%'
)
BEGIN
    SELECT RAISE(ABORT, 'The core system administrator must remain an active local owner');
END;

CREATE TRIGGER protect_system_admin_delete BEFORE DELETE ON users
WHEN OLD.is_system_admin = 1
BEGIN
    SELECT RAISE(ABORT, 'The core system administrator cannot be deleted');
END;

ALTER TABLE sessions ADD COLUMN id TEXT;
ALTER TABLE sessions ADD COLUMN method TEXT NOT NULL DEFAULT 'password' CHECK (method IN ('password', 'oidc', 'anonymous'));
UPDATE sessions SET id = lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-a' || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)));
UPDATE sessions SET method = 'anonymous' WHERE user_id = '00000000-0000-4000-8000-000000000001';
CREATE UNIQUE INDEX ix_sessions_public_id ON sessions(id);

CREATE TABLE oidc_transactions (
    state_hash TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    browser_hash TEXT NOT NULL,
    nonce TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
) STRICT;
CREATE INDEX ix_oidc_transactions_expiry ON oidc_transactions(expires_at);

CREATE TABLE external_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(issuer, subject)
) STRICT;
CREATE INDEX ix_external_identities_user ON external_identities(user_id);

CREATE TRIGGER protect_system_admin_oidc_insert BEFORE INSERT ON external_identities
WHEN EXISTS(SELECT 1 FROM users WHERE id = NEW.user_id AND is_system_admin = 1)
BEGIN
    SELECT RAISE(ABORT, 'The core system administrator uses local authentication only');
END;
CREATE TRIGGER protect_system_admin_oidc_update BEFORE UPDATE OF user_id ON external_identities
WHEN EXISTS(SELECT 1 FROM users WHERE id = NEW.user_id AND is_system_admin = 1)
BEGIN
    SELECT RAISE(ABORT, 'The core system administrator uses local authentication only');
END;
