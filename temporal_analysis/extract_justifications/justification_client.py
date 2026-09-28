"""Asks the model whether a report justifies a specific inconsistency (stage 3)."""

from __future__ import annotations

import time
from pathlib import Path

from google.genai import errors, types

from extraction.gemini_client import upload_pdf
from temporal_analysis.extract_justifications.justification_schema import JustificationResult

MAX_RETRIES = 5
RATE_LIMIT_DELAY_SECONDS = 30
BASE_DELAY_SECONDS = 2


def build_prompt(pattern: str, facts: dict) -> str:
    pattern_text = {
        "goalpost_shifting": (
            "The company changed an existing target (target value, target "
            "year or base year) before it was reached or expired."),
        "target_disbanding": (
            "The company silently dropped a still-running target; it is no "
            "longer reported."),
    }.get(pattern, pattern)

    fact_lines = "\n".join(line for line in [
        f"  - metric: {facts.get('metric')}" if facts.get('metric') else None,
        f"  - is_intensity_based: {facts.get('is_intensity_based')}"
            if facts.get('is_intensity_based') is not None else None,
        f"  - intensity_denominator: {facts.get('intensity_denominator')}"
            if facts.get('intensity_denominator') else None,
        f"  - target_direction: {facts.get('target_direction')}"
            if facts.get('target_direction') else None,
        f"  - target_year: {facts.get('target_year')}" if facts.get('target_year') else None,
        f"  - relative_target_value: {facts.get('relative_target_value')}"
            if facts.get('relative_target_value') else None,
        f"  - absolute_target_value: {facts.get('absolute_target_value')}"
            if facts.get('absolute_target_value') else None,
        f"  - base_year: {facts.get('base_year')}" if facts.get('base_year') else None,
        f"  - scope_1: {facts.get('scope_1')}" if facts.get('scope_1') is not None else None,
        f"  - scope_2: {facts.get('scope_2')}" if facts.get('scope_2') is not None else None,
        f"  - scope_3: {facts.get('scope_3')}" if facts.get('scope_3') is not None else None,
        f"  - scope_of_application: {facts.get('scope_of_application')}"
            if facts.get('scope_of_application') else None,
        f"  - emission_character: {facts.get('emission_character')}"
            if facts.get('emission_character') else None,
    ] if line is not None)

    return (
        "## General Instructions\n\n"
        "You are analysing a corporate sustainability report. A specific "
        "emission target was flagged as inconsistent. Determine whether this "
        "report contains an explicit justification for this change. A "
        "justification is an explanation the company gives for changing, "
        "moving or dropping the target (e.g. a new methodology, a revised "
        "strategy, an acquisition, a target under revision).\n\n"
        f"Pattern:\n{pattern_text}\n\n"
        f"Target details:\n{fact_lines}\n\n"
        "## Response Requirements\n\n"
        "- Quote the report verbatim. Do not summarise or paraphrase.\n"
        "- Copy the exact wording, so it can be found in the report by search.\n"
        "- Only count a real explanation for this change. A mere restatement of "
        "the new target, or unrelated sustainability text, is not a "
        "justification.\n"
        "- If in doubt, set found=false. Do not invent a justification.\n"
        "- If the report contains no justification for this specific change, set "
        "found=false and justification=null.\n"
        "- Give the 1-based page number where the quote appears.\n\n"
        "## Examples of Valid Justifications\n\n"
        "(from other reports, for illustration only)\n\n"
        '  1) "Beginning in 2016, we moved our baseline for evaluating emission '
        'reductions from 2010 levels back to 2005 levels to be consistent with '
        'how we report other air emissions."\n'
        '  2) "In 2020, we revised our greenhouse gas emissions goals and our '
        'target for the emissions from our value chain (scope 3) meets the '
        "Science Based Targets initiative's criteria for ambitious value chain "
        'goals, meaning they are in line with current best practice."\n'
    )


def _generate_with_retry(client, model_id, contents):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return client.models.generate_content(
                model=model_id,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=JustificationResult,
                ),
            )
        except errors.ClientError as exc:
            last_error = exc
            if getattr(exc, "code", None) == 429 and attempt < MAX_RETRIES - 1:
                time.sleep(RATE_LIMIT_DELAY_SECONDS)
                continue
            raise
        except (errors.ServerError, TimeoutError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(BASE_DELAY_SECONDS * (2 ** attempt))
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("generate_content returned no result and no error.")


def search_justification(client, model_id: str, pdf_path: Path, pattern: str,
                         facts: dict) -> JustificationResult | None:
    pdf = upload_pdf(client, pdf_path)
    try:
        response = _generate_with_retry(client, model_id, [pdf, build_prompt(pattern, facts)])
    finally:
        try:
            client.files.delete(name=pdf.name)
        except Exception:  # noqa: BLE001
            pass
    return response.parsed