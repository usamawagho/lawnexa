import sqlite3
from pathlib import Path
from datetime import datetime

source = Path("lawnexa.db").resolve()
if not source.exists():
    raise SystemExit(f"STOP: Database not found: {source}")

backup_dir = Path("backups")
backup_dir.mkdir(exist_ok=True)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = backup_dir / f"lawnexa_local_{stamp}.db"

src = sqlite3.connect(str(source))
dst = sqlite3.connect(str(backup))

try:
    src.backup(dst)
    result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    tables = dst.execute("""
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()

    print("Backup:", backup.resolve())
    print("Backup size:", backup.stat().st_size, "bytes")
    print("Integrity check:", result)
    print("Tables copied:", len(tables))
    print("Table names:", ", ".join(row[0] for row in tables))

    if result != "ok":
        raise SystemExit("STOP: Backup integrity check failed.")
finally:
    dst.close()
    src.close()
