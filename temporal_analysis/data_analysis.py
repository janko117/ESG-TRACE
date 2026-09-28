"""Summarises the results from targets_final in two tables, saves them to the
database and prints them.

report_company_summary has one row per company with the number of years,
targets, target paths and inconsistencies (and how many of them are justified).
report_inconsistencies has one row per inconsistency with the target, the
pattern and the justification.
"""

from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
import textwrap
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from shared import config  # noqa: E402

PATTERNS = [
    ("goalpost_shifting", "goalpost_shifting_direction",
     "goalpost_shifting_justification"),
    ("target_disbanding", None, "target_disbanding_justification"),
]


def is_empty(v):
    return v is None or str(v).strip() in ("", "NA", "None", "not_disclosed",
                                           "not_applicable")


def load_instances(con):
    """Load targets_final grouped by instance."""
    rows = con.execute(
        "SELECT instance_id, company, reported_year, indicator, value, "
        "evidence_report, evidence_page FROM targets_final"
    ).fetchall()
    inst = {}
    for iid, co, yr, ind, val, ereport, epage in rows:
        d = inst.setdefault(iid, {"company": co, "year": yr, "no_target": False,
                                  "fields": {}, "evidence": {}})
        if ind == "report_has_no_target" and str(val) in ("1", "1.0"):
            d["no_target"] = True
        else:
            d["fields"][ind] = val
            d["evidence"][ind] = (ereport, epage)
    return inst


def build_inconsistency_rows(inst):
    rows = []
    for iid, d in inst.items():
        if d["no_target"] or str(d["fields"].get("is_consistent")) != "0":
            continue
        f = d["fields"]
        for flag, direction_field, justification_field in PATTERNS:
            if str(f.get(flag)) != "1":
                continue
            justification = f.get(justification_field)
            ereport, epage = d["evidence"].get(justification_field, (None, None))
            rows.append({
                "company": d["company"],
                "reported_year": d["year"],
                "target_id": f.get("target_id"),
                "metric": f.get("metric"),
                "is_intensity_based": f.get("is_intensity_based"),
                "intensity_denominator": f.get("intensity_denominator"),
                "relative_target_value": f.get("relative_target_value"),
                "pattern": flag,
                "direction": f.get(direction_field) if direction_field else None,
                "justification": None if is_empty(justification) else justification,
                "evidence_report": ereport,
                "evidence_page": epage,
            })
    return sorted(rows, key=lambda r: (r["company"], r["reported_year"]))


def build_company_summary(inst):
    by_company = defaultdict(lambda: {
        "years": set(), "target_ids": set(), "n_instances": 0,
        "n_inconsistent": 0, "n_goalpost": 0, "n_goalpost_justified": 0,
        "n_disbanding": 0, "n_disbanding_justified": 0,
    })
    for iid, d in inst.items():
        if d["no_target"]:
            by_company[d["company"]]["years"].add(d["year"])
            continue
        f = d["fields"]
        c = by_company[d["company"]]
        c["years"].add(d["year"])
        c["n_instances"] += 1
        if f.get("target_id"):
            c["target_ids"].add(f["target_id"])
        if str(f.get("is_consistent")) == "0":
            c["n_inconsistent"] += 1
        if str(f.get("goalpost_shifting")) == "1":
            c["n_goalpost"] += 1
            if not is_empty(f.get("goalpost_shifting_justification")):
                c["n_goalpost_justified"] += 1
        if str(f.get("target_disbanding")) == "1":
            c["n_disbanding"] += 1
            if not is_empty(f.get("target_disbanding_justification")):
                c["n_disbanding_justified"] += 1

    rows = []
    for company, c in sorted(by_company.items()):
        rows.append({
            "company": company,
            "n_years": len(c["years"]),
            "n_instances": c["n_instances"],
            "n_paths": len(c["target_ids"]),
            "n_inconsistent": c["n_inconsistent"],
            "n_goalpost": c["n_goalpost"],
            "n_goalpost_justified": c["n_goalpost_justified"],
            "n_disbanding": c["n_disbanding"],
            "n_disbanding_justified": c["n_disbanding_justified"],
        })
    return rows


SUMMARY_COLUMNS = ["company", "n_years", "n_instances", "n_paths",
                   "n_inconsistent", "n_goalpost", "n_goalpost_justified",
                   "n_disbanding", "n_disbanding_justified"]

INCONSISTENCY_COLUMNS = ["company", "reported_year", "target_id", "metric",
                         "is_intensity_based", "intensity_denominator",
                         "relative_target_value", "pattern", "direction",
                         "justification", "evidence_report", "evidence_page"]


def write_table(con, table, columns, rows):
    col_defs = ", ".join(f"{c} TEXT" for c in columns)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"CREATE TABLE {table} ({col_defs})")
    placeholders = ",".join("?" * len(columns))
    con.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        [[r.get(c) for c in columns] for r in rows],
    )
    con.commit()


def _text(v):
    return "" if v is None else str(v)


def print_table(columns, rows):
    """Print rows as a simple aligned table."""
    cells = [columns] + [[_text(r.get(c)) for c in columns] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]
    for i, row in enumerate(cells):
        print("  ".join(v.ljust(w) for v, w in zip(row, widths)).rstrip())
        if i == 0:
            print("  ".join("-" * w for w in widths))


def print_inconsistencies(rows):
    """Print the inconsistencies as a table, with the justifications listed below."""
    table = []
    for i, r in enumerate(rows, 1):
        metric = _text(r["metric"])
        if str(r["is_intensity_based"]) == "1" and r["intensity_denominator"]:
            metric += f" per {r['intensity_denominator']}"
        table.append({"#": i, "company": r["company"], "year": r["reported_year"],
                      "target_id": r["target_id"], "metric": metric,
                      "target_value_%": r["relative_target_value"],
                      "pattern": r["pattern"], "direction": r["direction"]})
    print_table(["#", "company", "year", "target_id", "metric", "target_value_%",
                 "pattern", "direction"], table)

    print("\nJustifications:")
    for i, r in enumerate(rows, 1):
        if r["justification"]:
            source = f"{r['evidence_report'] or 'own report'}, p. {_text(r['evidence_page'])}"
            text = f"({source}) {r['justification']}"
        else:
            text = "none found"
        prefix = f"  [{i}] "
        print(textwrap.fill(text, width=100, initial_indent=prefix,
                            subsequent_indent=" " * len(prefix)))


def run(db_path):
    print(f"Database: {db_path}")
    con = sqlite3.connect(db_path)
    inst = load_instances(con)

    summary_rows = build_company_summary(inst)
    write_table(con, "report_company_summary", SUMMARY_COLUMNS, summary_rows)
    print(f"\n=== report_company_summary ({len(summary_rows)} row(s))\n")
    print_table(SUMMARY_COLUMNS, summary_rows)

    inconsistency_rows = build_inconsistency_rows(inst)
    write_table(con, "report_inconsistencies", INCONSISTENCY_COLUMNS,
                inconsistency_rows)
    print(f"\n=== report_inconsistencies ({len(inconsistency_rows)} row(s))\n")
    if inconsistency_rows:
        print_inconsistencies(inconsistency_rows)
    else:
        print("No inconsistencies found.")

    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(config.DB_PATH))
    args = p.parse_args()
    run(args.db)


if __name__ == "__main__":
    main()