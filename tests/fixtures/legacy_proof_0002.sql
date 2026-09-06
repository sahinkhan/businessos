-- Exact retained Phase 1 schema shape before database-role separation (f9239ae).
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

CREATE TABLE public.alembic_version (
    version_num varchar(32) PRIMARY KEY
);
INSERT INTO public.alembic_version (version_num) VALUES ('proof_0002');
