"""Step 2 of the extraction: check the batch job and store the results once it
has finished.

Reports that failed are submitted again automatically, at most
MAX_RETRY_ROUNDS times.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from shared import config, db_schema                              # noqa: E402
from shared.extraction_schema import ReportExtraction             # noqa: E402
from extraction import store                                      # noqa: E402
from extraction.extract_targets_batch import batch_common as bc   # noqa: E402
from extraction.gemini_client import build_client                 # noqa: E402
from extraction.report_register import load_register              # noqa: E402

MAX_RETRY_ROUNDS = 3


def run(cleanup: bool):
    state = bc.load_state(config.BATCH_STATE_PATH)
    client = build_client(config.GEMINI_API_KEY, config.REQUEST_TIMEOUT_S)
    job = bc.get_job(client, state["job_name"])

    status = getattr(job.state, "name", str(job.state))
    print(f"Job:      {state['job_name']}")
    print(f"Requests: {len(state['items'])}")
    print(f"Status:   {status}")

    if status != "JOB_STATE_SUCCEEDED":
        if status in bc.COMPLETED_STATES:
            print("\nJob finished, but not successfully. Nothing to collect.")
        else:
            print("\nStill in progress. Check again later (batch jobs can take up to 24 h).")
        return

    content = bc.download_bytes(client, job.dest.file_name).decode("utf-8")
    result_lines = [ln for ln in content.splitlines() if ln.strip()]
    bc.allow_long_int_parsing(100_000)

    entry_by_name = {e.report_name: e for e in load_register(config.REPORT_REGISTER_PATH)}
    model = state["model"]
    retry_round = state.get("retry_round", 0)

    db_schema.init_pipeline_db(config.DB_PATH)
    conn = sqlite3.connect(config.DB_PATH)
    if retry_round == 0:
        store.clear(conn)
    else:
        # Retry batch: only replace the reports that were submitted again
        for item in state["items"]:
            store.delete_report(conn, item["company"], item["report_name"])
    started_at = store.now_iso()

    iid = store.max_instance_id(conn) + 1
    n_ok, n_err = 0, 0
    seen = set()
    failed_keys = []
    for line in result_lines:
        r = bc.parse_result_line(line)
        key = r["key"]
        seen.add(key)
        entry = entry_by_name.get(key)
        if entry is None:
            print(f"  WARN: no report register entry for key {key}")
            continue

        if r["error"] or r["text"] is None:
            store.log_report(conn, model, started_at, entry, 0, "error",
                             str(r["error"]), "", r["in_tok"], r["out_tok"],
                             thought_text=r["thought_text"])
            n_err += 1
            failed_keys.append(key)
            print(f"  ERROR {entry.company} {key}: {r['error']}")
            continue

        try:
            extraction = ReportExtraction.model_validate(json.loads(r["text"]))
        except Exception as exc:  # noqa: BLE001
            store.log_report(conn, model, started_at, entry, 0, "error",
                             f"parse: {exc}", r["text"], r["in_tok"], r["out_tok"],
                             thought_text=r["thought_text"])
            n_err += 1
            failed_keys.append(key)
            print(f"  PARSE ERROR {entry.company} {key}: {exc}")
            continue

        iid = store.write_instances(conn, iid, entry, extraction, model)
        store.log_report(conn, model, started_at, entry, len(extraction.targets),
                         "ok", "", r["text"], r["in_tok"], r["out_tok"],
                         thought_text=r["thought_text"])
        n_ok += 1

    # Reports that were submitted but have no line in the result file
    for item in state["items"]:
        if item["key"] not in seen:
            entry = entry_by_name.get(item["key"])
            if entry is not None:
                store.log_report(conn, model, started_at, entry, 0, "error",
                                 "no result line", "", None, None)
                n_err += 1
                failed_keys.append(item["key"])

    in_sum, out_sum = store.token_sums(conn)
    conn.close()

    print(f"\nBatch complete.\n"
          f"Successful: {n_ok}, errors: {n_err}\n"
          f"Total tokens: input={in_sum}, output={out_sum}\n"
          f"Database: {config.DB_PATH}")

    if cleanup:
        _cleanup(client, state)

    if failed_keys and retry_round < MAX_RETRY_ROUNDS:
        print(f"\n{len(failed_keys)} report(s) failed. "
              f"Submitting retry batch (round {retry_round + 1}/{MAX_RETRY_ROUNDS}) ...")
        retry_entries = [entry_by_name[k] for k in failed_keys if k in entry_by_name]
        from extraction.extract_targets_batch.batch_submit import submit_reports
        submit_reports(retry_entries, model, retry_round=retry_round + 1)
        print("\nRetry batch submitted. Run batch_collect.py again once it has finished.")
    elif failed_keys:
        print(f"\n{len(failed_keys)} report(s) still failed after "
              f"{MAX_RETRY_ROUNDS} retry rounds. They remain logged as errors:")
        for k in failed_keys:
            print(f"  {k}")


def _cleanup(client, state):
    print("\nDeleting uploaded files ...")
    names = list(state.get("uploaded_files", {}).values()) + [state.get("input_file")]
    for fname in names:
        if not fname:
            continue
        try:
            client.files.delete(name=fname)
        except Exception as exc:  # noqa: BLE001
            print(f"  could not delete {fname}: {exc}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cleanup", action="store_true",
                   help="Delete the uploaded PDFs and the JSONL file after collecting.")
    run(p.parse_args().cleanup)


if __name__ == "__main__":
    main()
