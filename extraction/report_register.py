"""Reads the report register.

The CSV has one row per report with the columns company, report_name,
reported_year and report_length (number of pages). The matching PDF has to be
stored as data/reports/<company>/<report_name>.pdf.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from shared.config import PDF_ROOT


@dataclass
class ReportEntry:
    company: str
    report_name: str
    reported_year: int
    report_length: int
    pdf_path: Path

    def metadata(self) -> dict:
        return {
            "company": self.company,
            "report_name": self.report_name,
            "reported_year": self.reported_year,
            "report_length": self.report_length,
        }


def load_register(register_path: Path) -> list[ReportEntry]:
    entries: list[ReportEntry] = []
    with open(register_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            company = row["company"].strip()
            report_name = row["report_name"].strip()
            entries.append(ReportEntry(
                company=company,
                report_name=report_name,
                reported_year=int(row["reported_year"]),
                report_length=int(row["report_length"]),
                pdf_path=PDF_ROOT / company / f"{report_name}.pdf",
            ))
    return entries
