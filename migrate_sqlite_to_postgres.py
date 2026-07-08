import argparse
import os
import sqlite3
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:
    print("psycopg is required. Install dependencies with: pip install -r requirements.txt", file=sys.stderr)
    raise

import server


def quote_identifier(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def sqlite_tables(conn):
    return [
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        if not row["name"].startswith("sqlite_")
    ]


def sqlite_columns(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()]


def postgres_tables(conn):
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public' AND table_type='BASE TABLE'
            ORDER BY table_name
        """)
        return {row[0] for row in cursor.fetchall()}


def postgres_columns(conn, table):
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            ORDER BY ordinal_position
        """, (table,))
        return [row[0] for row in cursor.fetchall()]


def reset_sequence(conn, table):
    if "id" not in postgres_columns(conn, table):
        return
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
        sequence = cursor.fetchone()[0]
        if not sequence:
            return
        cursor.execute(f"SELECT COALESCE(MAX(id), 1) FROM {quote_identifier(table)}")
        max_id = int(cursor.fetchone()[0] or 1)
        cursor.execute("SELECT setval(%s, %s, true)", (sequence, max_id))


def migrate(source_path):
    if not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL must point to Railway PostgreSQL before running this migration.")

    source = Path(source_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"SQLite database not found: {source}")

    print(f"Initialising PostgreSQL schema from application code...")
    server.initialise()

    dsn = server.normalise_postgres_url(os.environ["DATABASE_URL"])
    copied = {}
    with sqlite3.connect(source) as sqlite_conn, psycopg.connect(dsn) as pg_conn:
        sqlite_conn.row_factory = sqlite3.Row
        target_tables = postgres_tables(pg_conn)
        for table in sqlite_tables(sqlite_conn):
            if table not in target_tables:
                print(f"Skipping {table}: table does not exist in PostgreSQL")
                continue
            source_columns = sqlite_columns(sqlite_conn, table)
            target_columns = postgres_columns(pg_conn, table)
            columns = [column for column in source_columns if column in target_columns]
            if not columns:
                print(f"Skipping {table}: no matching columns")
                continue
            rows = sqlite_conn.execute(f"SELECT {','.join(quote_identifier(column) for column in columns)} FROM {quote_identifier(table)}").fetchall()
            if not rows:
                copied[table] = 0
                continue
            placeholders = ",".join(["%s"] * len(columns))
            column_sql = ",".join(quote_identifier(column) for column in columns)
            insert_sql = f"INSERT INTO {quote_identifier(table)} ({column_sql}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            with pg_conn.cursor() as cursor:
                cursor.executemany(insert_sql, [tuple(row[column] for column in columns) for row in rows])
            reset_sequence(pg_conn, table)
            copied[table] = len(rows)
            print(f"Copied {len(rows)} row(s) from {table}")
        pg_conn.commit()
    return copied


def main():
    parser = argparse.ArgumentParser(description="Copy Sparkles SQLite data into Railway PostgreSQL.")
    parser.add_argument("--source", default=os.environ.get("SPARKLES_MIGRATION_SQLITE_PATH") or str(server.DB), help="Path to the SQLite sparkles.db file")
    args = parser.parse_args()
    copied = migrate(args.source)
    print("Migration complete.")
    for table, count in copied.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
