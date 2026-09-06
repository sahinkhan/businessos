-- Exact retained Phase 1 proof_0002 schema from
-- f9239aeb6a3182d539f7dda4612db2aa77ff0149. The caller creates the database
-- and its Docker-bootstrap-equivalent current_user role before applying this file.
CREATE SCHEMA eventing;
CREATE SCHEMA platform_module;
CREATE SCHEMA mod_example_phase1_proof;

CREATE TABLE eventing.outbox_messages (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    event_type varchar(200) NOT NULL,
    schema_version integer NOT NULL,
    occurred_at timestamptz NOT NULL,
    correlation_id varchar(100) NOT NULL,
    causation_id varchar(100),
    payload jsonb NOT NULL,
    published_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    last_error text
);
CREATE INDEX ix_outbox_messages_tenant_id ON eventing.outbox_messages (tenant_id);
CREATE INDEX ix_outbox_messages_unpublished ON eventing.outbox_messages (occurred_at)
WHERE published_at IS NULL;

CREATE TABLE eventing.inbox_receipts (
    consumer varchar(200) NOT NULL,
    event_id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_inbox_receipts PRIMARY KEY (consumer, event_id)
);
CREATE INDEX ix_inbox_receipts_tenant_id ON eventing.inbox_receipts (tenant_id);

CREATE TABLE platform_module.module_runtime_state (
    module_id varchar(200) PRIMARY KEY,
    version varchar(50) NOT NULL,
    state varchar(30) NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_error text
);

CREATE TABLE mod_example_phase1_proof.proof_records (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    value text NOT NULL,
    description text
);
CREATE INDEX ix_proof_records_tenant_id
ON mod_example_phase1_proof.proof_records (tenant_id);
ALTER TABLE mod_example_phase1_proof.proof_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY proof_records_tenant_isolation
ON mod_example_phase1_proof.proof_records
USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

CREATE TABLE public.alembic_version (
    version_num varchar(32) PRIMARY KEY
);
INSERT INTO public.alembic_version (version_num) VALUES ('proof_0002');

INSERT INTO mod_example_phase1_proof.proof_records
    (id, tenant_id, value, description)
VALUES
    ('11111111-1111-4111-8111-111111111111',
     'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
     'retained-value',
     'retained-description');

INSERT INTO eventing.outbox_messages
    (id, tenant_id, event_type, schema_version, occurred_at, correlation_id, payload)
VALUES
    ('22222222-2222-4222-8222-222222222222',
     'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
     'retained.event',
     1,
     '2026-09-06T07:44:21Z',
     'retained-proof-0002',
     '{}'::jsonb);
