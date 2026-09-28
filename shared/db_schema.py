"""Database schema.

Every stage writes its own table, all in the same long format (one row per
indicator and target instance):

    targets_extracted   output of the LLM extraction
    targets_derived     stage 1, with derived values
    targets_temporal    stage 2, with target paths and inconsistencies
    targets_final       stage 3, with justifications
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

TABLES = ("targets_extracted", "targets_derived", "targets_temporal", "targets_final")

# Fields the LLM extracts. sustainability_topic and metric_category are not
# asked for, stage 1 derives them.
EXTRACTED_FIELDS = [
    "metric", "is_intensity_based", "intensity_denominator", "target_direction",
    "relative_target_value", "absolute_target_value", "absolute_target_value_unit",
    "target_year", "base_year", "base_value", "base_value_unit",
    "annual_change_rate", "scope_of_application",
    "scope_1", "scope_2", "scope_3", "emission_character",
    "current_value", "current_value_unit", "current_relative_change",
    "achievement_rate", "achievement_status",
]

_ASPECT_GROUPS = {
    "Report Metadata": ["report_has_no_target"],
    "Target Content cross-dimensional": [
        "sustainability_topic", "metric_category", "metric", "is_intensity_based",
        "intensity_denominator", "target_direction",
        "relative_target_value", "absolute_target_value", "absolute_target_value_unit",
        "target_year", "base_year", "base_value", "base_value_unit",
        "annual_change_rate", "scope_of_application",
    ],
    "Target Content climate-specific": [
        "scope_1", "scope_2", "scope_3", "emission_character",
    ],
    "Target Status": [
        "current_value", "current_value_unit", "current_relative_change",
        "achievement_rate", "achievement_status",
    ],
    "Temporal Consistency": [
        "target_id", "target_version", "is_new_target", "last_mentioned",
        "is_consistent", "goalpost_shifting", "goalpost_shifting_direction",
        "goalpost_shifting_justification", "target_disbanding",
        "target_disbanding_justification",
    ],
}

ASPECT_MAP = {ind: aspect for aspect, inds in _ASPECT_GROUPS.items() for ind in inds}


def aspect_for(indicator: str):
    return ASPECT_MAP.get(indicator)


SCHEMA = """
CREATE TABLE IF NOT EXISTS {name} (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id       INTEGER NOT NULL,
    company           TEXT NOT NULL,
    report_name       TEXT,
    report_length     INTEGER,
    reported_year     INTEGER NOT NULL,
    extraction_method TEXT,
    aspect            TEXT,
    indicator         TEXT NOT NULL,
    value             TEXT,
    value_origin      TEXT,
    evidence_report   TEXT,
    evidence_page     INTEGER,
    evidence_type     TEXT,
    evidence_text     TEXT
);
CREATE INDEX IF NOT EXISTS idx_{name}_instance ON {name}(instance_id);
CREATE INDEX IF NOT EXISTS idx_{name}_company_year ON {name}(company, reported_year);
"""

ROW_COLUMNS = [
    "instance_id", "company", "report_name",
    "report_length", "reported_year", "extraction_method", "aspect",
    "indicator", "value", "value_origin",
    "evidence_report", "evidence_page", "evidence_type", "evidence_text",
]


def insert_row(cur, table: str, row: dict) -> None:
    """Insert one row. Keys missing in `row` are stored as NULL."""
    placeholders = ",".join("?" * len(ROW_COLUMNS))
    cur.execute(
        f"INSERT INTO {table} ({','.join(ROW_COLUMNS)}) VALUES ({placeholders})",
        [row.get(c) for c in ROW_COLUMNS],
    )


# Log table, one row per report sent to the model
EXTRACTION_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS extraction_reports (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id       TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    company        TEXT NOT NULL,
    report_name    TEXT NOT NULL,
    reported_year  INTEGER,
    n_targets      INTEGER,
    status         TEXT NOT NULL,
    error          TEXT,
    raw_json       TEXT,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    thought_text   TEXT
);
"""


def init_pipeline_db(path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("".join(SCHEMA.format(name=t) for t in TABLES) + EXTRACTION_LOG_SCHEMA)
    con.commit()
    con.close()
