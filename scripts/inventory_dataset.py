"""Schema-agnostic inventory of the official dataset directory.

Reads files under the data directory without modifying them and records, per file:
relative path, size, SHA-256, and for CSV/TSV the header and row count, for JSON the
top-level shape. It interprets no column and assumes no file name, so it is safe to
run before the dataset README has been read.

Default input is data/raw/ (the official archive, extracted unchanged); default output
is reports/dataset_inventory.json. The output may never be written inside the input
directory, so the raw dataset is never modified.

Exit codes:
    0  dataset directory found, non-empty, README present
    1  dataset directory found but no README-like file
    2  dataset directory missing or empty
    3  output path is inside the dataset directory (refused)
"""

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_OUT = PROJECT_ROOT / "reports" / "dataset_inventory.json"

DELIMITED = {".csv": ",", ".tsv": "\t"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_delimited(path: Path, delimiter: str) -> dict:
    csv.field_size_limit(sys.maxsize if sys.maxsize < 2**31 else 2**31 - 1)
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader, None)
        rows = sum(1 for _ in reader)
    return {"header": header or [], "column_count": len(header or []), "data_rows": rows}


def describe_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8-sig") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"json_error": str(exc)}
    if isinstance(doc, dict):
        return {"json_type": "object", "top_level_keys": sorted(doc)}
    if isinstance(doc, list):
        return {"json_type": "array", "length": len(doc)}
    return {"json_type": type(doc).__name__}


def inventory(data_dir: Path) -> dict:
    files = []
    for path in sorted(p for p in data_dir.rglob("*") if p.is_file()):
        if path.name == ".gitkeep":
            continue
        rel = path.relative_to(data_dir).as_posix()
        entry = {"path": rel, "bytes": path.stat().st_size, "sha256": sha256(path)}
        suffix = path.suffix.lower()
        if suffix in DELIMITED:
            entry.update(describe_delimited(path, DELIMITED[suffix]))
        elif suffix == ".json":
            entry.update(describe_json(path))
        elif suffix in {".zip", ".gz", ".tar", ".7z"}:
            entry["note"] = "archive: extract unchanged into data/raw/ and re-run"
        files.append(entry)
    readmes = [f["path"] for f in files if Path(f["path"]).name.lower().startswith("readme")]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(data_dir.resolve()),
        "file_count": len(files),
        "readme_candidates": readmes,
        "files": files,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.out.resolve().is_relative_to(args.data_dir.resolve()):
        print(f"REFUSED: output {args.out} is inside the dataset directory {args.data_dir}",
              file=sys.stderr)
        return 3
    if not args.data_dir.is_dir():
        print(f"BLOCKED: dataset directory not found: {args.data_dir}", file=sys.stderr)
        return 2
    report = inventory(args.data_dir)
    if report["file_count"] == 0:
        print(f"BLOCKED: dataset directory is empty: {args.data_dir}", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for f in report["files"]:
        shape = f"{f['data_rows']} rows x {f['column_count']} cols" if "data_rows" in f else ""
        print(f"{f['bytes']:>14,}  {f['path']}  {shape}")
    print(f"{report['file_count']} files; inventory written to {args.out}")

    if not report["readme_candidates"]:
        print("WARNING: no README-like file found; the README is authoritative and required.",
              file=sys.stderr)
        return 1
    print("README candidates: " + ", ".join(report["readme_candidates"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
