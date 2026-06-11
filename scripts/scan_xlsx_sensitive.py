"""Scan xlsx files for forbidden sensitive patterns (repository hygiene helper).

Usage: python scan_xlsx_sensitive.py <comma-separated-patterns> <xlsx> [<xlsx> ...]
Exits non-zero when any pattern is found in any cell.
"""
from __future__ import annotations

import sys

import openpyxl


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: scan_xlsx_sensitive.py <patterns> <xlsx> [<xlsx> ...]", file=sys.stderr)
        return 2

    patterns = [pattern.strip().lower() for pattern in sys.argv[1].split(",") if pattern.strip()]
    hits: list[str] = []
    for path in sys.argv[2:]:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for worksheet in workbook.worksheets:
                for row in worksheet.iter_rows(values_only=True):
                    for value in row:
                        if value is None:
                            continue
                        text = str(value).lower()
                        for pattern in patterns:
                            if pattern in text:
                                hits.append(f"{path} [{worksheet.title}]: {value}")
        finally:
            workbook.close()

    if hits:
        print("Forbidden sensitive pattern found in xlsx files:", file=sys.stderr)
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
