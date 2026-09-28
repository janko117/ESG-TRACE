"""Stores the extraction results in targets_extracted and logs every report in
extraction_reports."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from shared import db_schema
from shared.db_schema import EXTRACTED_FIELDS
from shared.extraction_schema import ReportExtraction


def _cell(value) -> str | None:
    """Convert a value for the TEXT column (2030.0 is stored as "2030")."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clear(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM targets_extracted")
    conn.execute("DELETE FROM extraction_reports")
    conn.commit()


def max_instance_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(instance_id) FROM targets_extracted").fetchone()
    return row[0] or 0


def delete_report(conn: sqlite3.Connection, company: str, report_name: str) -> None:
    """Delete all targets and log entries of a report, used before a retry."""
    conn.execute(
        "DELETE FROM targets_extracted WHERE company=? AND report_name=?",
        (company, report_name),
    )
    conn.execute(
        "DELETE FROM extraction_reports WHERE company=? AND report_name=?",
        (company, report_name),
    )
    conn.commit()


def log_report(conn, model_id, started_at, entry, n_targets, status, error, raw_json,
               in_tok, out_tok, thought_text=None) -> None:
    conn.execute(
        """INSERT INTO extraction_reports
           (model_id, started_at, company, report_name, reported_year, n_targets,
            status, error, raw_json, input_tokens, output_tokens, thought_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (model_id, started_at, entry.company, entry.report_name, entry.reported_year,
         n_targets, status, error, raw_json, in_tok, out_tok, thought_text),
    )
    conn.commit()


def token_sums(conn) -> tuple[int, int]:
    row = conn.execute(
        "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0) "
        "FROM extraction_reports"
    ).fetchone()
    return int(row[0]), int(row[1])


def write_instances(conn, start_instance_id: int, entry, extraction: ReportExtraction,
                    model_id: str) -> int:
    """Write the targets of one report and return the next free instance_id."""
    cur = conn.cursor()
    iid = start_instance_id

    def base_row(indicator):
        return {
            "instance_id": iid,
            "company": entry.company,
            "report_name": entry.report_name,
            "report_length": entry.report_length,
            "reported_year": entry.reported_year,
            "extraction_method": model_id,
            "aspect": db_schema.aspect_for(indicator),
            "indicator": indicator,
        }

    # No targets found: store a marker instance so the report still shows up
    if not extraction.targets:
        row = base_row("report_has_no_target")
        row.update({"value": "1", "value_origin": "extracted"})
        db_schema.insert_row(cur, "targets_extracted", row)
        conn.commit()
        return iid + 1

    for target in extraction.targets:
        data = target.model_dump(mode="json")

        field_evidence = {}
        for ev in data.get("evidence") or []:
            if isinstance(ev, dict) and isinstance(ev.get("field"), str):
                field_evidence[ev["field"]] = (ev.get("page"), ev.get("source_type"), ev.get("text"))

        for field in EXTRACTED_FIELDS:
            value = _cell(data.get(field))
            if value is None:
                continue
            ev_page, ev_type, ev_text = field_evidence.get(field, (None, None, None))
            row = base_row(field)
            row.update({
                "value": value,
                "value_origin": "extracted",
                "evidence_page": ev_page,
                "evidence_type": ev_type,
                "evidence_text": ev_text,
            })
            db_schema.insert_row(cur, "targets_extracted", row)
        iid += 1

    conn.commit()
    return iid
