"""Step 1 of the extraction: upload all reports from the register and start a
Gemini batch job."""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from shared import config                                         # noqa: E402
from extraction import store                                      # noqa: E402
from extraction.extract_targets_batch import batch_common as bc   # noqa: E402
from extraction.gemini_client import build_client, upload_pdf     # noqa: E402
from extraction.prompts import prompt_extract_targets             # noqa: E402
from extraction.report_register import load_register              # noqa: E402


def submit_reports(entries, model, retry_round=0):
    """Submit the reports as one batch job and save the job state.

    retry_round is only > 0 when batch_collect.py submits failed reports again.
    """
    client = build_client(config.GEMINI_API_KEY, config.REQUEST_TIMEOUT_S)
    schema = bc.response_schema_dict()

    tag = f"retry {retry_round}" if retry_round else "initial"
    print(f"Model={model}, Reports={len(entries)} ({tag})")
    print("Uploading reports and building requests ...")

    lines, items, uploaded_files = [], [], {}
    for i, entry in enumerate(entries, 1):
        if not entry.pdf_path.exists():
            print(f"  [{i}/{len(entries)}] PDF missing, skipped: {entry.pdf_path}")
            continue
        pdf = upload_pdf(client, entry.pdf_path)
        prompt_text = prompt_extract_targets(entry.metadata())
        lines.append(bc.build_request_line(entry.report_name, prompt_text, pdf.uri, schema))
        items.append({"key": entry.report_name, "company": entry.company,
                      "report_name": entry.report_name, "reported_year": entry.reported_year})
        uploaded_files[entry.report_name] = pdf.name
        print(f"  [{i}/{len(entries)}] {entry.company} {entry.report_name}")

    if not lines:
        print("No requests created (no PDFs found). Aborting.")
        return None

    bc.write_jsonl(config.BATCH_INPUT_PATH, lines)
    print(f"\nJSONL written: {config.BATCH_INPUT_PATH} ({len(lines)} request(s))")

    display = "extract_targets" + (f"_retry{retry_round}" if retry_round else "")
    input_file = bc.upload_jsonl(client, config.BATCH_INPUT_PATH, display)
    job = bc.create_batch(client, model, input_file.name, display)

    bc.save_state(config.BATCH_STATE_PATH, {
        "job_name": job.name,
        "model": model,
        "input_file": input_file.name,
        "uploaded_files": uploaded_files,
        "items": items,
        "created_at": store.now_iso(),
        "retry_round": retry_round,
    })

    print(f"\nBatch job created: {job.name}")
    print(f"State saved: {config.BATCH_STATE_PATH}")
    print("\nNext step: batch_collect.py (checks the status, collects once the job has succeeded)")
    return job.name


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--register", default=str(config.REPORT_REGISTER_PATH))
    p.add_argument("--model", default=config.MODEL_ID)
    p.add_argument("--limit", type=int, default=None,
                   help="Submit only the first N reports (for test runs).")
    args = p.parse_args()

    entries = load_register(pathlib.Path(args.register))
    if args.limit is not None:
        entries = entries[: args.limit]
    submit_reports(entries, args.model)


if __name__ == "__main__":
    main()
