-- Executed as the schema owner after every successful Alembic upgrade.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM kglearn_app;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM kglearn_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO kglearn_app;
GRANT UPDATE (password_hash, must_change_password, password_changed_at) ON users TO kglearn_app;
GRANT INSERT ON sessions, exercise_attempts, learning_events, qa_records TO kglearn_app;
GRANT UPDATE (revoked_at) ON sessions TO kglearn_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO kglearn_app;
