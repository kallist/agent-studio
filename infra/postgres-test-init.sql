-- Disposable negative-path database used to prove that pgvector startup fails clearly.
-- These credentials have no use outside the loopback-only tmpfs test container.
CREATE ROLE agent_studio_limited_test LOGIN PASSWORD 'not-a-secret-test-only';
CREATE DATABASE agent_studio_no_vector_test OWNER agent_studio_test;
REVOKE CREATE ON DATABASE agent_studio_no_vector_test FROM PUBLIC;
REVOKE CREATE ON DATABASE agent_studio_no_vector_test FROM agent_studio_limited_test;

\connect agent_studio_no_vector_test

GRANT USAGE, CREATE ON SCHEMA public TO agent_studio_limited_test;
