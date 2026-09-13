from __future__ import annotations

import argparse
import json
from pathlib import Path

from .db import init_db
from .ml_foundation import export_ml_dataset_csv, ml_status


def main() -> None:
    p = argparse.ArgumentParser(description="Export Trade Zone V6.4 ML foundation dataset.")
    p.add_argument("--out", default="tradezone_ml_dataset.csv", help="CSV output path")
    p.add_argument("--limit", type=int, default=None, help="Maximum rows (capped by ML_DATASET_EXPORT_LIMIT)")
    p.add_argument("--status-only", action="store_true", help="Print collector status without exporting")
    args = p.parse_args()

    init_db()
    status = ml_status()
    print(json.dumps(status, indent=2, sort_keys=True))
    if args.status_only:
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(export_ml_dataset_csv(args.limit), encoding="utf-8", newline="")
    print(f"Exported ML dataset to {out.resolve()}")


if __name__ == "__main__":
    main()
