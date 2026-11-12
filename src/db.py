"""Database connectivity (PyMySQL only, raw parameterised SQL)."""
import os

import pymysql
import pymysql.cursors


def get_db_config():
    """Database settings in one place (environment variables or defaults)."""
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASS", ""),
        "database": os.environ.get("DB_NAME", "icc_rankings"),
        "charset": "utf8mb4",
    }


def get_connection():
    return pymysql.connect(**get_db_config(),
                           cursorclass=pymysql.cursors.DictCursor,
                           autocommit=False)


def query(sql, params=()):
    """READ: run one SELECT and return all rows as dicts."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def query_one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(statements):
    """WRITE: run [(sql, params), ...] as ONE transaction; all or nothing.
    Returns the total number of affected rows."""
    conn = get_connection()
    total = 0
    try:
        with conn.cursor() as cur:
            for sql, params in statements:
                total += cur.execute(sql, params)
        conn.commit()
        return total
    except pymysql.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def error_text(e):
    """Turn a PyMySQL error into a readable message for flash()."""
    if isinstance(e, pymysql.err.MySQLError) and len(e.args) >= 2:
        code, msg = e.args[0], e.args[1]
        friendly = {
            1062: "That record already exists (duplicate key).",
            1451: "It is still referenced by other records (history is kept, so the delete is refused).",
            1452: "A referenced record does not exist.",
            3819: "A value breaks a CHECK constraint.",
            1048: "A required value is missing.",
            1406: "A value is too long.",
            1265: "A value is not allowed for that field.",
        }.get(code)
        return f"{friendly + ' ' if friendly else ''}[MySQL {code}] {msg}"
    return str(e)
