"""Run from the repository root: python scripts/check_deployment.py."""

from importlib import metadata
from pathlib import Path
import json
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    """Проверить зависимости, структуру проекта и целостность SQLite без сетевых запросов."""
    errors = []
    print("Python:", sys.version.split()[0], flush=True)
    if not (3, 11) <= sys.version_info[:2] <= (3, 14):
        errors.append(
            "Use Python 3.12 for the documented deployment (supported: 3.11–3.14)."
        )
    for package in ("streamlit", "pandas", "plotly"):
        try:
            print(f"{package}: {metadata.version(package)}", flush=True)
        except metadata.PackageNotFoundError:
            errors.append(f"Missing {package}; run pip install -r requirements.txt")
    for name in (
        "app.py",
        "nobel/storage.py",
        "nobel/geography.py",
        "nobel/exports.py",
        ".streamlit/config.toml",
        "static/world_110m.json",
    ):
        if not (ROOT / name).is_file():
            errors.append(f"Missing file: {name}")
    conflicts = [
        name
        for name in ("uv.lock", "Pipfile", "environment.yml", "environment.yaml")
        if (ROOT / name).exists()
    ]
    if conflicts:
        errors.append(
            "Other dependency manifests can take precedence in Cloud: "
            + ", ".join(conflicts)
        )
    db = ROOT / "nobel_database.sqlite"
    if not db.is_file():
        errors.append("Missing nobel_database.sqlite")
    else:
        try:
            with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
                if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    errors.append("SQLite quick_check failed")
                if conn.execute("PRAGMA foreign_key_check").fetchall():
                    errors.append("Broken database foreign keys")
                meta = {
                    key: json.loads(value)
                    for key, value in conn.execute("SELECT key,value FROM metadata")
                }
                if meta.get("schema_version") != 2:
                    errors.append("Unsupported database schema")
                print(
                    "Snapshot:",
                    meta.get("updated_at"),
                    "laureates:",
                    meta.get("laureate_count"),
                    flush=True,
                )
        except (sqlite3.Error, ValueError) as exc:
            errors.append(f"Cannot read database: {exc}")
    if errors:
        for error in errors:
            print("ERROR:", error, file=sys.stderr)
        return 1
    print("Deployment file and database checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
