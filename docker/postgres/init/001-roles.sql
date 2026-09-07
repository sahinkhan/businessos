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
END
$$;

ALTER ROLE businessos_migrator
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
ALTER ROLE businessos_app
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
ALTER ROLE businessos_ops
    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS;

REVOKE businessos_migrator, businessos_ops FROM businessos_app;
REVOKE ALL ON DATABASE businessos FROM PUBLIC;
GRANT CONNECT ON DATABASE businessos TO businessos_migrator, businessos_app, businessos_ops;
ALTER DATABASE businessos OWNER TO businessos_migrator;
ALTER SCHEMA public OWNER TO businessos_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
