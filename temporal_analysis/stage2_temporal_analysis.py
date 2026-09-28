"""Stage 2: link the targets of consecutive years into target paths and detect
goalpost shifting and target disbanding.

Reads targets_derived and writes targets_temporal.
"""

from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from shared import config, db_schema                                   # noqa: E402
from temporal_analysis.stage1_derive_fields import CONTENT_INDICATORS  # noqa: E402

# The justification fields are added later in stage 3
TEMPORAL_INDICATORS = [
    "target_id", "target_version", "is_new_target", "last_mentioned",
    "is_consistent",
    "goalpost_shifting", "goalpost_shifting_direction",
    "target_disbanding",
]

CO2_GHG_COMPATIBLE = {"CO2", "GHG"}
SENTINEL = 1e15


def load_derived(con):
    cur = con.cursor()
    cur.execute("""
        SELECT instance_id, company, reported_year, indicator,
               value, value_origin, evidence_report, evidence_page,
               evidence_type, evidence_text,
               report_name, report_length, extraction_method
        FROM targets_derived
        ORDER BY company, reported_year, instance_id, id
    """)
    instances = {}
    for row in cur.fetchall():
        (iid, co, yr, ind, val, vo, er, ep, et, ex,
         rname, rlen, emeth) = row
        if iid not in instances:
            instances[iid] = {"company": co, "reported_year": yr,
                              "report_name": rname, "report_length": rlen,
                              "extraction_method": emeth,
                              "fields": {}, "is_no_target": False}
        instances[iid]["fields"][ind] = {
            "value": val, "value_origin": vo,
            "evidence_report": er, "evidence_page": ep,
            "evidence_type": et, "evidence_text": ex,
        }
        if ind == "report_has_no_target" and str(val) in ("1", "1.0"):
            instances[iid]["is_no_target"] = True
    return instances


def group_by_company_year(instances):
    tmp = defaultdict(lambda: defaultdict(list))
    for iid, inst in instances.items():
        tmp[inst["company"]][inst["reported_year"]].append(iid)
    result = {}
    for co, years in tmp.items():
        result[co] = sorted((yr, ids) for yr, ids in years.items())
    return result


def is_empty(v):
    return v is None or str(v).strip() in ("", "NA", "None", "not_disclosed", "not_applicable")


def is_valid_target(fields):
    """Check if an instance is a complete target.

    That means it has a metric, a target year and a relative target value.
    Everything else is left out of the path linking.
    """
    return (not is_empty(get_val(fields, "metric"))
            and to_float(get_val(fields, "target_year")) is not None
            and to_float(get_val(fields, "relative_target_value")) is not None)


def get_val(fields, field):
    return fields.get(field, {}).get("value")


def to_float(v):
    if is_empty(v):
        return None
    try:
        f = float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None
    # NaN or inf (e.g. from an endless digit string) is not a usable value
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def to_int(v):
    f = to_float(v)
    return int(f) if f is not None else None


def normalize_binary(v):
    if is_empty(v):
        return None
    s = str(v).strip()
    if s in ("1", "1.0"):
        return 1
    if s in ("0", "0.0"):
        return 0
    return None


def matches_identity(a_fields, b_fields):
    # sustainability_topic has to match exactly
    va = str(a_fields.get("sustainability_topic", {}).get("value") or "").strip()
    vb = str(b_fields.get("sustainability_topic", {}).get("value") or "").strip()
    if va != vb:
        return False

    # Here a missing value on one side is fine
    for f in ("is_intensity_based", "target_direction"):
        va = str(a_fields.get(f, {}).get("value") or "").strip()
        vb = str(b_fields.get(f, {}).get("value") or "").strip()
        if va == "" or vb == "":
            continue
        if va != vb:
            return False

    ma = a_fields.get("metric_category", {}).get("value")
    mb = b_fields.get("metric_category", {}).get("value")
    if ma != mb:
        if not (ma in CO2_GHG_COMPATIBLE and mb in CO2_GHG_COMPATIBLE):
            return False

    for f in ("scope_1", "scope_2", "scope_3"):
        va = normalize_binary(a_fields.get(f, {}).get("value"))
        vb = normalize_binary(b_fields.get(f, {}).get("value"))
        if va is None or vb is None:
            continue
        if va != vb:
            return False

    # A net target (offsets included) is a different target than a gross one.
    # Gross and "not stated" count as the same.
    ea = str(a_fields.get("emission_character", {}).get("value") or "").strip().lower()
    eb = str(b_fields.get("emission_character", {}).get("value") or "").strip().lower()
    if (ea == "net") != (eb == "net"):
        return False

    return True


def similarity(a, b, scale):
    """1 for equal values, 0 if they differ by `scale` or more."""
    return 1 - min(abs(to_float(a) - to_float(b)) / scale, 1)


def match_cost(path_fields, target_fields):
    """Cost of linking an instance to a path, between 0 (same target) and 1.

    Target year and relative target value count equally. A difference of
    10 years or 100 percentage points counts as completely different.
    """
    sim_year = similarity(get_val(path_fields, "target_year"),
                          get_val(target_fields, "target_year"), 10)
    sim_value = similarity(get_val(path_fields, "relative_target_value"),
                           get_val(target_fields, "relative_target_value"), 100)
    return 1 - (0.5 * sim_year + 0.5 * sim_value)


def is_eligible(inst_fields, path_fields):
    if not matches_identity(inst_fields, path_fields):
        return False
    prev_ach = str(get_val(path_fields, "achievement_status") or "").lower()
    if prev_ach == "achieved" and not instance_unchanged(path_fields, inst_fields):
        return False
    return True


def optimal_assignment(cand_iids, cand_paths, instances):
    eligible = {}
    for iid in cand_iids:
        inst = instances[iid]
        elig = [p for p in cand_paths if is_eligible(inst["fields"], p["last_instance"]["fields"])]
        if elig:
            eligible[iid] = elig

    if not eligible:
        return {}

    rows = list(eligible.keys())
    cols = []
    for plist in eligible.values():
        for p in plist:
            if p not in cols:
                cols.append(p)

    cost = np.full((len(rows), len(cols)), SENTINEL)
    for i, iid in enumerate(rows):
        inst = instances[iid]
        for j, p in enumerate(cols):
            if p in eligible[iid]:
                cost[i, j] = match_cost(p["last_instance"]["fields"], inst["fields"])

    row_ind, col_ind = linear_sum_assignment(cost)

    assignment = {}
    for r, c in zip(row_ind, col_ind):
        if cost[r, c] < SENTINEL:
            assignment[rows[r]] = cols[c]
    return assignment


def annual_change_rate(fields):
    rtv = to_float(fields.get("relative_target_value", {}).get("value"))
    ty = to_int(fields.get("target_year", {}).get("value"))
    by = to_int(fields.get("base_year", {}).get("value"))
    if rtv is None or ty is None or by is None or ty == by:
        return None
    return rtv / (ty - by)


def detect_goalpost(prev_fields, curr_fields):
    for f in ("relative_target_value", "target_year", "base_year"):
        vp = to_float(prev_fields.get(f, {}).get("value"))
        vc = to_float(curr_fields.get(f, {}).get("value"))
        if vp is None or vc is None:
            continue
        if f == "relative_target_value":
            # Ignore differences below 1 % (rounding)
            denom = max(abs(vp), abs(vc))
            if denom > 0 and abs(vp - vc) <= 0.01 * denom:
                continue
            if vp != vc:
                return True
        else:
            if vp != vc:
                return True
    return False


def goalpost_direction(prev_fields, curr_fields):
    rp = annual_change_rate(prev_fields)
    rc = annual_change_rate(curr_fields)
    if rp is not None and rc is not None:
        if abs(rc - rp) < 1e-6:
            return "unchanged"
        return "tightening" if rc > rp else "loosening"
    return "unclear"


def instance_unchanged(prev_fields, curr_fields):
    for f in ("relative_target_value", "target_year", "base_year"):
        vp = to_float(prev_fields.get(f, {}).get("value"))
        vc = to_float(curr_fields.get(f, {}).get("value"))
        if vp != vc:
            return False
    return True


def _attach_instance(path, iid, inst):
    prev = path["last_instance"]["fields"]
    curr = inst["fields"]
    gs = detect_goalpost(prev, curr)
    inst["target_id"] = path["target_id"]
    inst["is_new_target"] = 0
    inst["goalpost_shifting"] = 1 if gs else 0
    if gs:
        path["version"] += 1
        inst["goalpost_shifting_direction"] = goalpost_direction(prev, curr)
    else:
        inst["goalpost_shifting_direction"] = None
    inst["target_version"] = f"V{path['version']}"
    path["last_year"] = inst["reported_year"]
    path["last_instance"] = inst
    path["instances"].append(iid)


def process_company(company, years_data, instances):
    paths = []
    next_pid = 1

    all_years = [yr for yr, _ in years_data]
    first_year = all_years[0]
    last_year = all_years[-1]

    # Assign each instance to a path from the previous year. Instances without
    # a match start a new path.
    n_removed = 0
    for yr, iids in years_data:
        available = [p for p in paths if p["last_year"] == yr - 1]
        real_iids = []
        for iid in iids:
            if instances[iid]["is_no_target"]:
                continue
            if not is_valid_target(instances[iid]["fields"]):
                instances[iid]["excluded_incomplete"] = True
                n_removed += 1
                continue
            real_iids.append(iid)

        assignment = optimal_assignment(real_iids, available, instances)

        for iid, path in assignment.items():
            _attach_instance(path, iid, instances[iid])

        for iid in real_iids:
            if iid in assignment:
                continue
            inst = instances[iid]
            path = {
                "target_id": f"T{next_pid}",
                "version": 1,
                "last_year": yr,
                "last_instance": inst,
                "instances": [iid],
            }
            next_pid += 1
            paths.append(path)
            inst["target_id"] = path["target_id"]
            inst["target_version"] = "V1"
            inst["is_new_target"] = None if yr == first_year else 1
            inst["goalpost_shifting"] = None if yr == first_year else 0
            inst["goalpost_shifting_direction"] = None

    # A path that ends before the last report year counts as disbanded,
    # unless the target was already achieved or failed
    for p in paths:
        last_iid = p["instances"][-1]
        last_inst = instances[last_iid]
        for iid in p["instances"][:-1]:
            instances[iid]["last_mentioned"] = 0
            instances[iid]["target_disbanding"] = 0

        ach = str(get_val(last_inst["fields"], "achievement_status") or "").lower()

        if p["last_year"] == last_year:
            last_inst["last_mentioned"] = None
            if ach in ("achieved", "failed"):
                last_inst["target_disbanding"] = 0
            else:
                last_inst["target_disbanding"] = None
        else:
            last_inst["last_mentioned"] = 1
            if ach in ("achieved", "failed"):
                last_inst["target_disbanding"] = 0
            else:
                last_inst["target_disbanding"] = 1

    # An instance only counts as inconsistent if one of the patterns was found
    for iid, inst in instances.items():
        if inst["company"] != company:
            continue
        if inst["is_no_target"]:
            continue
        gs = inst.get("goalpost_shifting")
        td = inst.get("target_disbanding")
        if gs == 1 or td == 1:
            inst["is_consistent"] = 0
        else:
            inst["is_consistent"] = 1

    return n_removed


def write_temporal(instances, con):
    cur = con.cursor()
    cur.execute("DELETE FROM targets_temporal")

    def base_row(inst, indicator):
        return {
            "instance_id": None,
            "company": inst["company"],
            "report_name": inst.get("report_name"),
            "report_length": inst.get("report_length"),
            "reported_year": inst["reported_year"],
            "extraction_method": inst.get("extraction_method"),
            "aspect": db_schema.aspect_for(indicator),
            "indicator": indicator,
        }

    for iid in sorted(instances):
        inst = instances[iid]

        if inst.get("excluded_incomplete"):
            continue

        if inst["is_no_target"]:
            data = inst["fields"].get("report_has_no_target", {})
            row = base_row(inst, "report_has_no_target")
            row.update({
                "instance_id": iid, "value": "1", "value_origin": "extracted",
                "evidence_report": data.get("evidence_report"),
                "evidence_page": data.get("evidence_page"),
                "evidence_type": data.get("evidence_type"),
                "evidence_text": data.get("evidence_text"),
            })
            db_schema.insert_row(cur, "targets_temporal", row)
            continue

        for indicator in CONTENT_INDICATORS:
            data = inst["fields"].get(indicator, {})
            row = base_row(inst, indicator)
            row.update({
                "instance_id": iid,
                "value": None if is_empty(data.get("value")) else str(data.get("value")),
                "value_origin": data.get("value_origin"),
                "evidence_report": data.get("evidence_report"),
                "evidence_page": data.get("evidence_page"),
                "evidence_type": data.get("evidence_type"),
                "evidence_text": data.get("evidence_text"),
            })
            db_schema.insert_row(cur, "targets_temporal", row)

        for indicator in TEMPORAL_INDICATORS:
            val = inst.get(indicator)
            row = base_row(inst, indicator)
            row.update({
                "instance_id": iid,
                "value": None if val is None else str(val),
                "value_origin": "derived_rule" if val is not None else None,
            })
            db_schema.insert_row(cur, "targets_temporal", row)

    con.commit()


def run(db_path):
    db_schema.init_pipeline_db(db_path)
    con = sqlite3.connect(db_path)
    instances = load_derived(con)
    by_company = group_by_company_year(instances)
    n_removed_total = 0
    for co, years_data in by_company.items():
        n_removed_total += process_company(co, years_data, instances)
    write_temporal(instances, con)
    con.close()
    if n_removed_total:
        print(f"Stage 2: excluded {n_removed_total} incomplete instance(s) "
              f"(missing metric, target_year or relative_target_value).")
    print(f"Stage 2 complete: {len(instances) - n_removed_total} instance(s) "
          f"in targets_temporal ({db_path})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(config.DB_PATH))
    args = parser.parse_args()
    print(f"Database: {args.db}")
    run(args.db)
