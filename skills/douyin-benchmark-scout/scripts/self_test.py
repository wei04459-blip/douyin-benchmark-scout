#!/usr/bin/env python3
"""Offline smoke test: workbook, classification, headers and privacy patterns."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
ASSETS = ROOT / "assets"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="douyin-scout-test-") as tmp:
        output = Path(tmp) / "synthetic.xlsx"
        preview = Path(tmp) / "preview"
        env = os.environ.copy()
        env.update({
            "BENCHMARK_MANIFEST": str(ASSETS / "synthetic-manifest.json"),
            "BENCHMARK_ANALYSIS": str(ASSETS / "synthetic-analysis.json"),
            "BENCHMARK_INPUT_XLSX": "",
            "BENCHMARK_OUTPUT_XLSX": str(output),
            "BENCHMARK_PREVIEW_DIR": str(preview),
        })
        subprocess.run([sys.executable, str(SCRIPTS / "build_workbook.py")], env=env, check=True)
        wb = load_workbook(output, data_only=False)
        source = wb["竞品选题分析"]
        assert source.max_column == 30
        assert source["AC2"].value == "S｜低粉高爆"
        assert wb["重点关注账号"].max_row == 16
        assert (preview / "竞品选题分析.html").is_file()
    forbidden = [
        "/Users/" + "yuwan",
        "yuwan" + "-knowledge-base",
        "api" + "-business",
        "BEGIN " + "PRIVATE KEY",
        "gh" + "p_",
    ]
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".py", ".md", ".json", ".yaml", ".yml", ".mjs"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            matches = [token for token in forbidden if token in text]
            if matches:
                raise AssertionError(f"Privacy pattern in {path}: {matches}")
    print("SELF_TEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
