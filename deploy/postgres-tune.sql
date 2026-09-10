-- ReciApp Postgres on a 1g container / NVMe. Requires restart for
-- shared_buffers and max_connections.
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '768MB';
ALTER SYSTEM SET max_connections = '40';
ALTER SYSTEM SET wal_compression = 'on';
ALTER SYSTEM SET random_page_cost = '1.1';
ALTER SYSTEM SET effective_io_concurrency = '200';
ALTER SYSTEM SET checkpoint_completion_target = '0.9';
ALTER SYSTEM SET huge_pages = 'off';
ALTER SYSTEM SET idle_in_transaction_session_timeout = '30s';
