-- Database initialization script
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    display_name VARCHAR(128),
    email VARCHAR(128),
    role VARCHAR(32) NOT NULL DEFAULT 'zone_viewer'
        CHECK (role IN ('super_admin', 'zone_admin', 'zone_operator', 'zone_viewer', 'approver')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Zones metadata table
CREATE TABLE IF NOT EXISTS zones (
    id SERIAL PRIMARY KEY,
    zone_name VARCHAR(255) UNIQUE NOT NULL,
    zone_type VARCHAR(16) NOT NULL DEFAULT 'master'
        CHECK (zone_type IN ('master', 'slave', 'hint', 'forward')),
    view_name VARCHAR(64) NOT NULL DEFAULT 'external',
    file_name VARCHAR(255),
    named_conf_entry TEXT,
    record_count INTEGER DEFAULT 0,
    last_serial VARCHAR(16),
    last_modified TIMESTAMP DEFAULT NOW(),
    last_modified_by INTEGER REFERENCES users(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- User-Zone access assignments
CREATE TABLE IF NOT EXISTS user_zone_access (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    zone_id INTEGER REFERENCES zones(id) ON DELETE CASCADE,
    zone_pattern VARCHAR(255),
    permissions TEXT[] DEFAULT '{}',
    UNIQUE(user_id, zone_id)
);

-- Audit log (append-only, no UPDATE/DELETE)
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    username VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    zone_name VARCHAR(255),
    target_record TEXT,
    before_value TEXT,
    after_value TEXT,
    ssh_command TEXT,
    ssh_output TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'success',
    ip_address VARCHAR(45),
    timestamp TIMESTAMP DEFAULT NOW()
);

-- Approval workflow (change requests)
CREATE TABLE IF NOT EXISTS change_requests (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) NOT NULL,
    action VARCHAR(32) NOT NULL,
    zone_name VARCHAR(255) NOT NULL,
    payload JSONB,
    status VARCHAR(16) DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'executed', 'failed')),
    approver_id INTEGER REFERENCES users(id),
    submitted_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP,
    executed_at TIMESTAMP,
    review_comment TEXT
);

-- Zone file backups (for rollback)
CREATE TABLE IF NOT EXISTS zone_backups (
    id BIGSERIAL PRIMARY KEY,
    zone_name VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    serial VARCHAR(16),
    backed_up_by INTEGER REFERENCES users(id),
    backup_type VARCHAR(16) DEFAULT 'pre_change',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Session store
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(512) UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create audit log protection trigger (prevent UPDATE/DELETE)
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit log is append-only. UPDATE and DELETE are not allowed.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_no_update ON audit_log;
CREATE TRIGGER trg_audit_no_update
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH STATEMENT
    EXECUTE FUNCTION prevent_audit_modification();

DROP TRIGGER IF EXISTS trg_backups_no_update ON zone_backups;
CREATE TRIGGER trg_backups_no_update
    BEFORE UPDATE OR DELETE ON zone_backups
    FOR EACH STATEMENT
    EXECUTE FUNCTION prevent_audit_modification();

-- Insert default super_admin user (password: admin123, bcrypt hash)
INSERT INTO users (username, password_hash, display_name, role, email)
VALUES ('admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj2NXZCO7m0a', 'Super Admin', 'super_admin', 'admin@cnooc.com')
ON CONFLICT (username) DO NOTHING;
