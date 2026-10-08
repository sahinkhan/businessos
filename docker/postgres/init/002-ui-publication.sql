\set ON_ERROR_STOP on

-- Development bootstrap only. Production operators provision their own secret
-- through the database-role transition command before the forward migration.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='businessos_ui_publication') THEN
        CREATE ROLE businessos_ui_publication LOGIN NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOINHERIT NOBYPASSRLS NOREPLICATION
            PASSWORD 'businessos-ui-publication';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='businessos_metadata_fence_owner') THEN
        CREATE ROLE businessos_metadata_fence_owner NOLOGIN NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOINHERIT NOBYPASSRLS NOREPLICATION;
    END IF;
END $$;
GRANT businessos_metadata_fence_owner TO businessos_migrator WITH INHERIT TRUE, SET TRUE;
GRANT CONNECT ON DATABASE businessos TO businessos_ui_publication;
