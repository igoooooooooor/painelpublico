"""Find 23-field payroll-shaped records without printing their contents."""

from __future__ import annotations

import argparse
import ast
import csv
import json
from pathlib import Path
from typing import Any, Iterable


FIELD_COUNT = 23


def _walk_json(value: Any, location: str = "") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}" if location else str(key)
            yield from _walk_json(child, child_location)
    elif isinstance(value, list):
        if len(value) == FIELD_COUNT and all(
            not isinstance(item, (dict, list)) for item in value
        ):
            yield "json_scalar_array_23", location, value
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{location}[{index}]")
    elif isinstance(value, str):
        yield "string", location, value


def _line_categories(line: str, expected_fields: list[str]) -> list[str]:
    matches: list[str] = []
    for delimiter, category in (
        (";", "semicolon_23"),
        (",", "comma_23"),
        ("\t", "tab_23"),
    ):
        if delimiter not in line:
            continue
        try:
            fields = next(csv.reader([line], delimiter=delimiter))
        except (csv.Error, StopIteration):
            continue
        if len(fields) == FIELD_COUNT and fields != expected_fields:
            matches.append(category)

    stripped = line.strip()
    if stripped.count("|") >= FIELD_COUNT - 1:
        fields = stripped.strip("|").split("|")
        if len(fields) == FIELD_COUNT:
            matches.append("pipe_23")

    if stripped.startswith(("[", "(")) and stripped.endswith(("]", ")")):
        try:
            value = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            value = None
        if (
            isinstance(value, (list, tuple))
            and len(value) == FIELD_COUNT
            and all(not isinstance(item, (dict, list, tuple)) for item in value)
            and value != expected_fields
        ):
            matches.append("python_sequence_23")
    return matches


def _collect_file(path: Path, expected_fields: list[str]) -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {}

    def record(category: str, location: str) -> None:
        findings.setdefault(category, []).append(location)

    def scan_text(text: str, location_prefix: str) -> None:
        for line_number, line in enumerate(text.splitlines(), 1):
            for category in _line_categories(line, expected_fields):
                record(category, f"{location_prefix}:line{line_number}")

    raw = path.read_bytes()
    if path.suffix == ".jsonl":
        for event_number, raw_line in enumerate(raw.splitlines(), 1):
            try:
                event = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            for category, location, value in _walk_json(event):
                if category == "string":
                    scan_text(value, f"event{event_number}:{location}")
                elif value != expected_fields:
                    record(category, f"event{event_number}:{location}")
        return findings

    if path.suffix == ".json":
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            value = None
        if value is not None:
            for category, location, item in _walk_json(value):
                if category == "string":
                    scan_text(item, location)
                elif item != expected_fields:
                    record(category, location)
            return findings

    scan_text(raw.decode("utf-8", errors="replace"), "file")
    return findings


def _expand_paths(paths: list[Path], repo_root: Path) -> list[Path]:
    requested = [
        repo_root / "data/raw/mandate-cost",
        repo_root / "data/snapshots",
        *repo_root.rglob("__pycache__"),
        *paths,
    ]
    expanded: list[Path] = []
    for requested_path in requested:
        if requested_path.is_dir():
            expanded.extend(path for path in requested_path.rglob("*") if path.is_file())
        else:
            expanded.append(requested_path)
    return sorted(set(expanded), key=str)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    schema_path = repo_root / "data/raw/mandate-cost/senate-pilot/csv-schema.json"
    try:
        expected_fields = json.loads(schema_path.read_text(encoding="utf-8"))["fields"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        print(f"Could not load expected CSV schema: {type(error).__name__}")
        return 2
    if not isinstance(expected_fields, list) or len(expected_fields) != FIELD_COUNT:
        print("Expected CSV schema must contain exactly 23 field labels.")
        return 2

    parser = argparse.ArgumentParser(
        description="Report locations of 23-field candidates without printing row contents."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="additional files or directories; defaults to local cache, snapshots, and __pycache__",
    )
    args = parser.parse_args()
    files = _expand_paths(args.paths, repo_root)
    unreadable = 0
    candidates = 0
    for path in files:
        try:
            findings = _collect_file(path, expected_fields)
        except OSError as error:
            unreadable += 1
            print(f"UNREADABLE {path} ({type(error).__name__})")
            continue
        if not findings:
            continue
        candidates += 1
        print(f"FILE {path}")
        for category, locations in sorted(findings.items()):
            print(f"  {category}: count={len(locations)} locations={locations[:20]}")

    print(f"files_scanned={len(files)} candidate_files={candidates} unreadable_files={unreadable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
