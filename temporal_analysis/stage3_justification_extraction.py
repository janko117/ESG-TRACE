"""Stage 3: look for justifications of the inconsistencies found in stage 2.

targets_final is rebuilt as a copy of targets_temporal plus one justification
row per inconsistency. For goalpost shifting only the instance's own report is
searched. For target disbanding the following year's report is searched too if
the own report has nothing. Its name is then stored in evidence_report.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import config, db_schema  # noqa: E402
from extraction.gemini_client import build_client  # noqa: E402
from extraction.report_register import load_register  # noqa: E402
from temporal_analysis.extract_justifications.justification_client import search_justification  # noqa: E402

PATTERN_TO_JUSTIFICATION = {
    "goalpost_shifting": "goalpost_shifting_justification",
    "target_disbanding": "target_disbanding_justification",
}

# Passed to the model so it knows which target is meant
FACT_INDICATORS = [
    "metric", "is_intensity_based", "intensity_denominator", "target_direction",
    "relative_target_value", "absolute_target_value", "target_year",
    "base_year", "scope_1", "scope_2", "scope_3", "scope_of_application",
    "emission_character",
]


def load_instances(con):
    """Load targets_temporal grouped by instance."""
    cur = con.execute(
        "SELECT instance_id, company, reported_year, report_name, indicator, value "
        "FROM targets_temporal")
    inst = {}
    for iid, co, yr, rname, ind, val in cur.fetchall():
        d = inst.setdefault(iid, {"company": co, "year": yr,
                                  "report_name": rname, "fields": {}})
        d["fields"][ind] = val
    return inst


def report_index(register):
    by_name = {e.report_name: e for e in register}
    by_co_year = {(e.company, int(e.reported_year)): e for e in register}
    return by_name, by_co_year


def facts_for(inst):
    f = inst["fields"]
    facts = {"company": inst["company"], "reported_year": inst["year"]}
    for ind in FACT_INDICATORS:
        if f.get(ind) not in (None, "", "NA"):
            facts[ind] = f[ind]
    return facts


def load_base_rows(con):
    cols = ("instance_id, company, report_name, report_length, "
            "reported_year, extraction_method, aspect, "
            "indicator, value, value_origin, evidence_report, evidence_page, "
            "evidence_type, evidence_text")
    cur = con.execute(f"SELECT {cols} FROM targets_temporal")
    names = [c.strip() for c in cols.split(",")]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def instance_meta(base_rows):
    """Report metadata for each instance, needed for the new justification rows."""
    meta = {}
    for r in base_rows:
        iid = r["instance_id"]
        if iid not in meta:
            meta[iid] = {k: r[k] for k in (
                "instance_id", "company", "report_name", "report_length",
                "reported_year", "extraction_method")}
    return meta


def rebuild_final_from_temporal(con, base_rows):
    con.execute("DELETE FROM targets_final")
    cur = con.cursor()
    for r in base_rows:
        db_schema.insert_row(cur, "targets_final", r)
    con.commit()


def is_found(result):
    return result is not None and result.found and bool(result.justification)


def insert_justification(con, meta, iid, indicator, result, evidence_report):
    row = dict(meta[iid])
    row["indicator"] = indicator
    row["aspect"] = db_schema.aspect_for(indicator)
    if is_found(result):
        quote = result.justification.strip()
        row.update({
            "value": quote, "value_origin": "extracted",
            "evidence_page": result.evidence_page, "evidence_type": "text",
            "evidence_text": quote, "evidence_report": evidence_report,
        })
    else:
        row.update({"value": None, "value_origin": "not_disclosed"})
    db_schema.insert_row(con.cursor(), "targets_final", row)
    con.commit()


def process(con, client, model, register):
    inst = load_instances(con)
    base_rows = load_base_rows(con)
    meta = instance_meta(base_rows)
    by_name, by_co_year = report_index(register)

    rebuild_final_from_temporal(con, base_rows)

    inconsistent = [(iid, d) for iid, d in inst.items()
                    if str(d["fields"].get("is_consistent")) == "0"]
    print(f"{len(inconsistent)} inconsistent instance(s) to process.")

    n_found = 0
    for iid, d in inconsistent:
        facts = facts_for(d)
        own = by_name.get(d["report_name"])
        if own is None or not own.pdf_path.exists():
            print(f"  instance {iid}: own report missing, skipped")
            continue

        for pattern, indicator in PATTERN_TO_JUSTIFICATION.items():
            if str(d["fields"].get(pattern)) != "1":
                continue

            result = search_justification(client, model, own.pdf_path, pattern, facts)
            if is_found(result):
                insert_justification(con, meta, iid, indicator, result, evidence_report=None)
                n_found += 1
                print(f"  instance {iid} [{pattern}]: found in own report")
                continue

            if pattern == "target_disbanding":
                follow = by_co_year.get((d["company"], int(d["year"]) + 1))
                if follow is not None and follow.pdf_path.exists():
                    result = search_justification(client, model, follow.pdf_path, pattern, facts)
                    if is_found(result):
                        insert_justification(con, meta, iid, indicator, result,
                                             evidence_report=follow.report_name)
                        n_found += 1
                        print(f"  instance {iid} [{pattern}]: found in "
                              f"following report {follow.report_name}")
                        continue

            insert_justification(con, meta, iid, indicator, None, evidence_report=None)
            print(f"  instance {iid} [{pattern}]: no justification")

    print(f"Done. Justifications found: {n_found}")


def run(db_path, model=config.MODEL_ID, register_path=config.REPORT_REGISTER_PATH):
    client = build_client(config.GEMINI_API_KEY, config.REQUEST_TIMEOUT_S)
    register = load_register(Path(register_path))
    db_schema.init_pipeline_db(db_path)
    con = sqlite3.connect(db_path)
    process(con, client, model, register)
    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(config.DB_PATH))
    p.add_argument("--model", default=config.MODEL_ID)
    p.add_argument("--register", default=str(config.REPORT_REGISTER_PATH))
    args = p.parse_args()

    print(f"Database: {args.db}")
    run(args.db, args.model, args.register)


if __name__ == "__main__":
    main()
