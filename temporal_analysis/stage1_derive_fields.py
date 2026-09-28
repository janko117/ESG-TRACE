"""Stage 1: fill in missing values that can be derived from the extracted ones.

Reads targets_extracted and writes targets_derived. Extracted values are never
overwritten. Derived values are marked with value_origin "derived_rule" or
"derived_calc".
"""

from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from shared import config, db_schema  # noqa: E402

CONTENT_INDICATORS = [
    "sustainability_topic", "metric_category", "metric", "is_intensity_based",
    "intensity_denominator", "target_direction",
    "relative_target_value", "absolute_target_value", "absolute_target_value_unit",
    "target_year", "base_year", "base_value", "base_value_unit",
    "annual_change_rate", "scope_of_application",
    "scope_1", "scope_2", "scope_3", "emission_character",
    "current_value", "current_value_unit", "current_relative_change",
    "achievement_rate", "achievement_status",
]


def load_instances(con, table):
    cur = con.cursor()
    cur.execute(f"""
        SELECT instance_id, indicator, value, value_origin,
               company, reported_year,
               report_name, report_length, extraction_method,
               evidence_report, evidence_page, evidence_type, evidence_text
        FROM {table}
        ORDER BY instance_id, id
    """)
    instances = defaultdict(dict)
    meta = {}
    for row in cur.fetchall():
        (iid, ind, val, vo, co, yr, rname, rlen, emeth,
         er, ep, et, ex) = row
        instances[iid][ind] = {"value": val, "value_origin": vo,
                               "evidence_report": er,
                               "evidence_page": ep, "evidence_type": et,
                               "evidence_text": ex}
        if iid not in meta:
            meta[iid] = {"company": co, "reported_year": yr, "report_name": rname,
                         "report_length": rlen, "extraction_method": emeth}
    return instances, meta


def is_empty(v):
    return v is None or str(v).strip() in ("", "NA", "None", "not_disclosed", "not_applicable")


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


def derive_metric_category(instance):
    if not is_empty(instance.get("metric_category", {}).get("value")):
        return None
    metric = str(instance.get("metric", {}).get("value") or "").lower()
    if not metric:
        return None
    if "co2e" in metric or "co2 equivalent" in metric or "co₂e" in metric \
            or ("carbon dioxide" in metric and "equivalent" in metric):
        return ("GHG", "derived_rule")
    if "ghg" in metric or "greenhouse gas" in metric:
        return ("GHG", "derived_rule")
    if "co2" in metric or "co₂" in metric or "carbon dioxide" in metric:
        return ("CO2", "derived_rule")
    if "carbon" in metric:
        return ("GHG", "derived_rule")
    if "emission" in metric:
        return ("GHG", "derived_rule")
    return None


def derive_sustainability_topic(instance):
    if not is_empty(instance.get("sustainability_topic", {}).get("value")):
        return None
    mc = instance.get("metric_category", {}).get("value")
    if mc in ("CO2", "GHG"):
        return ("climate_change", "derived_rule")
    return None


def derive_relative_target_value(instance):
    if not is_empty(instance.get("relative_target_value", {}).get("value")):
        return None
    bv = to_float(instance.get("base_value", {}).get("value"))
    atv = to_float(instance.get("absolute_target_value", {}).get("value"))
    direction = str(instance.get("target_direction", {}).get("value") or "").lower()
    if bv is not None and atv is not None and bv != 0:
        if direction == "reduction":
            return (round((bv - atv) / bv * 100, 2), "derived_calc")
        if direction == "increase":
            return (round((atv - bv) / bv * 100, 2), "derived_calc")

    acr = to_float(instance.get("annual_change_rate", {}).get("value"))
    ty = to_int(instance.get("target_year", {}).get("value"))
    by = to_int(instance.get("base_year", {}).get("value"))
    if acr is not None and ty is not None and by is not None and bv is None and atv is None:
        return (round(acr * (ty - by), 2), "derived_calc")
    return None


def derive_absolute_target_value(instance):
    if not is_empty(instance.get("absolute_target_value", {}).get("value")):
        return None
    bv = to_float(instance.get("base_value", {}).get("value"))
    rtv = to_float(instance.get("relative_target_value", {}).get("value"))
    direction = str(instance.get("target_direction", {}).get("value") or "").lower()
    if bv is None or rtv is None:
        return None
    if direction == "reduction":
        return (round(bv * (1 - rtv / 100), 4), "derived_calc")
    if direction == "increase":
        return (round(bv * (1 + rtv / 100), 4), "derived_calc")
    return None


def derive_absolute_target_value_unit(instance):
    if not is_empty(instance.get("absolute_target_value_unit", {}).get("value")):
        return None
    bvu = instance.get("base_value_unit", {}).get("value")
    if is_empty(bvu):
        return None
    return (bvu, "derived_rule")


def derive_annual_change_rate(instance):
    if not is_empty(instance.get("annual_change_rate", {}).get("value")):
        return None
    rtv = to_float(instance.get("relative_target_value", {}).get("value"))
    ty = to_int(instance.get("target_year", {}).get("value"))
    by = to_int(instance.get("base_year", {}).get("value"))
    if rtv is None or ty is None or by is None or ty == by:
        return None
    return (round(rtv / (ty - by), 3), "derived_calc")


def derive_current_relative_change(instance):
    if not is_empty(instance.get("current_relative_change", {}).get("value")):
        return None
    cv = to_float(instance.get("current_value", {}).get("value"))
    bv = to_float(instance.get("base_value", {}).get("value"))
    direction = str(instance.get("target_direction", {}).get("value") or "").lower()
    if cv is None or bv is None or bv == 0:
        return None
    if direction == "reduction":
        return (round((bv - cv) / bv * 100, 2), "derived_calc")
    if direction == "increase":
        return (round((cv - bv) / bv * 100, 2), "derived_calc")
    return None


def derive_achievement_rate(instance):
    if not is_empty(instance.get("achievement_rate", {}).get("value")):
        return None
    crc = to_float(instance.get("current_relative_change", {}).get("value"))
    rtv = to_float(instance.get("relative_target_value", {}).get("value"))
    if crc is None or rtv is None or rtv == 0:
        return None
    return (round(crc / rtv, 3), "derived_calc")


def derive_achievement_status(instance, reported_year):
    if not is_empty(instance.get("achievement_status", {}).get("value")):
        return None
    ar = to_float(instance.get("achievement_rate", {}).get("value"))
    ty = to_int(instance.get("target_year", {}).get("value"))
    if ar is None:
        return ("ongoing", "derived_rule")
    if ar >= 1:
        return ("achieved", "derived_rule")
    if ty is not None and reported_year is not None and reported_year >= ty and ar < 1:
        return ("failed", "derived_rule")
    return ("ongoing", "derived_rule")


def apply_derivations(instances, meta):
    for iid, inst in instances.items():
        yr = meta[iid]["reported_year"]
        for indicator, deriver, needs_year in [
            ("metric_category", derive_metric_category, False),
            ("sustainability_topic", derive_sustainability_topic, False),
            ("relative_target_value", derive_relative_target_value, False),
            ("absolute_target_value", derive_absolute_target_value, False),
            ("absolute_target_value_unit", derive_absolute_target_value_unit, False),
            ("annual_change_rate", derive_annual_change_rate, False),
            ("current_relative_change", derive_current_relative_change, False),
            ("achievement_rate", derive_achievement_rate, False),
            ("achievement_status", derive_achievement_status, True),
        ]:
            result = deriver(inst, yr) if needs_year else deriver(inst)
            if result is not None:
                val, origin = result
                if indicator not in inst:
                    inst[indicator] = {}
                inst[indicator]["value"] = val
                inst[indicator]["value_origin"] = origin
    return instances


def write_derived(instances, meta, con, table_out):
    cur = con.cursor()
    cur.execute(f"DELETE FROM {table_out}")

    def base_row(m, indicator):
        return {
            "instance_id": None,
            "company": m["company"],
            "report_name": m.get("report_name"),
            "report_length": m.get("report_length"),
            "reported_year": m["reported_year"],
            "extraction_method": m.get("extraction_method"),
            "aspect": db_schema.aspect_for(indicator),
            "indicator": indicator,
        }

    for iid in sorted(instances):
        inst = instances[iid]
        m = meta[iid]

        if "report_has_no_target" in inst:
            data = inst["report_has_no_target"]
            row = base_row(m, "report_has_no_target")
            row.update({
                "instance_id": iid,
                "value": None if is_empty(data.get("value")) else str(data.get("value")),
                "value_origin": data.get("value_origin"),
                "evidence_report": data.get("evidence_report"),
                "evidence_page": data.get("evidence_page"),
                "evidence_type": data.get("evidence_type"),
                "evidence_text": data.get("evidence_text"),
            })
            db_schema.insert_row(cur, table_out, row)
            continue

        for indicator in CONTENT_INDICATORS:
            data = inst.get(indicator, {})
            row = base_row(m, indicator)
            row.update({
                "instance_id": iid,
                "value": None if is_empty(data.get("value")) else str(data.get("value")),
                "value_origin": data.get("value_origin"),
                "evidence_report": data.get("evidence_report"),
                "evidence_page": data.get("evidence_page"),
                "evidence_type": data.get("evidence_type"),
                "evidence_text": data.get("evidence_text"),
            })
            db_schema.insert_row(cur, table_out, row)
    con.commit()


def run(db_path, table_in="targets_extracted", table_out="targets_derived"):
    db_schema.init_pipeline_db(db_path)
    con = sqlite3.connect(db_path)
    instances, meta = load_instances(con, table_in)
    apply_derivations(instances, meta)
    write_derived(instances, meta, con, table_out)
    con.close()
    print(f"Stage 1 complete: {len(instances)} instance(s) in {table_out} ({db_path})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(config.DB_PATH))
    args = parser.parse_args()
    print(f"Database: {args.db}")
    run(args.db)