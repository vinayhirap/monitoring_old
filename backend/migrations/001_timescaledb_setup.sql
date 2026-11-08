-- ============================================================================
-- TimescaleDB setup — converts the OHLCV time-series table to a hypertable.
-- ============================================================================
--
-- Run AFTER:
--   1. Postgres + TimescaleDB extension are installed
--   2. The app has been pointed at the new Postgres DATABASE_URL and started
--      once so SQLAlchemy creates the base tables (CREATE TABLE IF NOT EXISTS)
--   3. The new DB is empty OR you've already imported the SQLite data
--      (see 002_migrate_from_sqlite.sql for that path)
--
-- Why TimescaleDB:
--   • The `ohlcv_bars` table grows fast: ~3M rows per year at 500 symbols × 250
--     trading days × 6 timeframes. SQLite and vanilla Postgres handle this
--     adequately but range queries get slow.
--   • TimescaleDB partitions automatically by time chunks. Range queries on
--     recent data scan a tiny chunk instead of the full table.
--   • Built-in compression (8-12× typical) on chunks older than N days —
--     keep 30 days hot, compress everything older.
--
-- ============================================================================

-- 1. Enable the extension. Must run as a superuser the first time.
CREATE EXTENSION IF NOT EXISTS timescaledb;


-- 2. Convert ohlcv_bars to a hypertable.
--    `chunk_time_interval` of 7 days is right for our query pattern (most
--    requests look at last N days). Adjust if you ever do month-range queries.
--    `if_not_exists` lets this script run idempotently.
SELECT create_hypertable(
    'ohlcv_bars',          -- table name
    'ts',                  -- time-dimension column
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE,
    migrate_data => TRUE   -- moves existing rows into chunks during conversion
);


-- 3. Compression policy — anything older than 30 days gets compressed.
--    Hypertable compression is column-oriented + delta-of-delta encoded,
--    typically 8-12× shrinkage on OHLCV data.
ALTER TABLE ohlcv_bars SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'symbol, timeframe'
);

SELECT add_compression_policy(
    'ohlcv_bars',
    INTERVAL '30 days',
    if_not_exists => TRUE
);


-- 4. Retention policy — drop data older than 5 years. Adjust upward if you
--    need longer history. Daily-timeframe data is small (~125KB/symbol/year)
--    so 5 years is generous.
SELECT add_retention_policy(
    'ohlcv_bars',
    INTERVAL '5 years',
    if_not_exists => TRUE
);


-- 5. Indices specific to our access pattern. The composite index on
--    (symbol, timeframe, ts DESC) is what the read path uses most.
CREATE INDEX IF NOT EXISTS ix_ohlcv_sym_tf_ts_desc
    ON ohlcv_bars (symbol, timeframe, ts DESC);


-- 6. (Optional) Continuous aggregate for daily summary.
--    Pre-aggregates intraday data into daily bars at write time. Speeds up
--    the dashboard's daily view by ~100×. Comment out if you don't use
--    intraday timeframes.
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_daily_summary
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket(INTERVAL '1 day', ts) AS day,
    FIRST(open, ts)  AS open,
    MAX(high)        AS high,
    MIN(low)         AS low,
    LAST(close, ts)  AS close,
    SUM(volume)      AS volume
FROM ohlcv_bars
WHERE timeframe IN ('15m', '5m', '1m')
GROUP BY symbol, day;

SELECT add_continuous_aggregate_policy(
    'ohlcv_daily_summary',
    start_offset => INTERVAL '30 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);


-- ============================================================================
-- Verification queries — run these to confirm the migration succeeded.
-- ============================================================================
-- SELECT hypertable_name, num_chunks, compression_enabled
--   FROM timescaledb_information.hypertables
--   WHERE hypertable_name = 'ohlcv_bars';
--
-- SELECT chunk_name, range_start, range_end, is_compressed
--   FROM timescaledb_information.chunks
--   WHERE hypertable_name = 'ohlcv_bars'
--   ORDER BY range_start DESC LIMIT 10;
--
-- SELECT pg_size_pretty(pg_total_relation_size('ohlcv_bars')) AS total_size;
-- ============================================================================
