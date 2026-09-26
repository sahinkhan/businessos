\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'businessos_migrator') THEN
        CREATE ROLE businessos_migrator
            LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS
            PASSWORD 'businessos-migration';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'businessos_app') THEN
        CREATE ROLE businessos_app
            LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS
            PASSWORD 'businessos-application';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'businessos_ops') THEN
        CREATE ROLE businessos_ops
            LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS
            PASSWORD 'businessos-operations';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'businessos_worker') THEN
        CREATE ROLE businessos_worker
            LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS
            PASSWORD 'businessos-worker';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'businessos_governance') THEN
        CREATE ROLE businessos_governance
            LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS
            PASSWORD 'businessos-governance';
    END IF;
END
$$;

ALTER ROLE businessos_migrator
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
ALTER ROLE businessos_app
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
ALTER ROLE businessos_ops
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS;
ALTER ROLE businessos_worker
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS;
ALTER ROLE businessos_governance
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

REVOKE businessos_migrator, businessos_ops FROM businessos_app;
REVOKE businessos_migrator, businessos_ops FROM businessos_worker;
GRANT businessos_app TO businessos_worker;
REVOKE businessos_governance FROM businessos_app, businessos_worker, businessos_migrator, businessos_ops;
REVOKE businessos_app, businessos_worker, businessos_migrator, businessos_ops FROM businessos_governance;
REVOKE ALL ON DATABASE businessos FROM PUBLIC;
GRANT CONNECT ON DATABASE businessos TO businessos_migrator, businessos_app, businessos_ops, businessos_worker, businessos_governance;
ALTER DATABASE businessos OWNER TO businessos_migrator;
ALTER SCHEMA public OWNER TO businessos_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
