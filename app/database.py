import sqlite3
from contextlib import contextmanager
from typing import Generator
from app.config import DATABASE_PATH

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Configure WAL mode and busy timeout for high concurrency
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db() -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. Rules table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY,
                keyword TEXT UNIQUE NOT NULL,
                dm_message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        
        # 2. Events table (Raw event dedup)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
        """)
        
        # 3. Deletion tombstones table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deleted_comments (
                comment_id TEXT PRIMARY KEY,
                deleted_at TEXT NOT NULL
            );
        """)
        
        # 4. DM jobs outbox table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dm_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                comment_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', 
                attempt_count INTEGER DEFAULT 0,
                idempotency_key TEXT UNIQUE NOT NULL,
                dm_id TEXT NULL,
                next_attempt_at TEXT NULL,
                lease_until TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CONSTRAINT uq_user_rule UNIQUE(user_id, rule_id)
            );
        """)
        
        # Create index on status & next_attempt_at for fast polling
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dm_jobs_status ON dm_jobs(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dm_jobs_user_rule ON dm_jobs(user_id, rule_id);")

        # 5. Duplicates log table (for accurate GET /stats tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS duplicates_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NULL,
                user_id TEXT NULL,
                rule_id TEXT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
