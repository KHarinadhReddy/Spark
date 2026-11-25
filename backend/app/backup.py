from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings


def create_backup(output_dir: Path, keep: int = 14) -> Path:
    """Snapshot SQLite safely, then bundle it with the OAuth token.

    SQLite's online backup API is used instead of copying the file, so a
    running API/worker cannot leave a torn database in the archive.
    """
    settings = Settings.load()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = output_dir / f"spark-backup-{stamp}.zip"
    snapshot = output_dir / f".spark-{stamp}.db"

    try:
        with sqlite3.connect(settings.db_path) as source:
            with sqlite3.connect(snapshot) as destination:
                source.backup(destination)
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "db_path": str(settings.db_path),
            "google_token_included": settings.google_token_path.exists(),
            "mode": settings.mode,
        }
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(snapshot, "spark.db")
            if settings.google_token_path.exists():
                bundle.write(settings.google_token_path, "google_token.json")
            if settings.mock_state_path.exists():
                bundle.write(settings.mock_state_path, "mock_workspace.json")
            bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
    finally:
        snapshot.unlink(missing_ok=True)

    _prune(output_dir, keep)
    return archive


def _prune(output_dir: Path, keep: int) -> None:
    if keep <= 0:
        return
    archives = sorted(output_dir.glob("spark-backup-*.zip"))
    for old in archives[:-keep]:
        old.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up Spark's SQLite store.")
    parser.add_argument(
        "--output",
        default="/backup",
        help="Directory that receives spark-backup-*.zip (default: /backup)",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=14,
        help="Number of archives to keep (default: 14, 0 disables pruning)",
    )
    args = parser.parse_args()
    archive = create_backup(Path(args.output), keep=args.keep)
    print(archive)


if __name__ == "__main__":
    main()
