"""Paths and settings for the pipeline."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ModuleNotFoundError:
    pass

DATA = PROJECT_ROOT / "data"

# One row per report
REPORT_REGISTER_PATH = DATA / "report_register" / "report_register.csv"

# PDFs are expected in data/reports/<company>/<report_name>.pdf
PDF_ROOT = DATA / "reports"

DB_PATH = DATA / "databases" / "pipeline.db"

# Written by batch_submit.py, read by batch_collect.py
BATCH_STATE_PATH = DATA / "databases" / "batch_state.json"
BATCH_INPUT_PATH = DATA / "databases" / "batch_input.jsonl"

# Model for the extraction and the justification search,
# e.g. "gemini-3.6-flash" or "gemini-3.5-flash-lite"
MODEL_ID = "gemini-3.6-flash"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Also store the model's thought summary for each report
CAPTURE_THOUGHTS = True

# Timeout per API call (seconds)
REQUEST_TIMEOUT_S = 180
