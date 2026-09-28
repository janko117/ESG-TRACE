"""Helper functions for the Gemini Batch API."""

from __future__ import annotations

import json
import pathlib
import sys

from shared import config

COMPLETED_STATES = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
                    "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


def allow_long_int_parsing(max_digits: int = 1_000_000) -> None:
    """Raise Python's limit for long integers.

    Otherwise json.loads fails when the model produces a number with thousands
    of digits.
    """
    setter = getattr(sys, "set_int_max_str_digits", None)
    if setter is None:
        return
    try:
        if sys.get_int_max_str_digits() < max_digits:
            setter(max_digits)
    except Exception:  # noqa: BLE001
        pass


def save_state(path, data: dict) -> None:
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_state(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_request_line(key: str, prompt_text: str, file_uri: str, schema: dict) -> dict:
    """Build the JSONL request for one report (uploaded PDF plus prompt)."""
    generation_config = {
        "responseMimeType": "application/json",
        "responseSchema": schema,
    }
    if config.CAPTURE_THOUGHTS:
        generation_config["thinkingConfig"] = {"includeThoughts": True}
    return {
        "key": key,
        "request": {
            "contents": [{"role": "user", "parts": [
                {"fileData": {"fileUri": file_uri, "mimeType": "application/pdf"}},
                {"text": prompt_text},
            ]}],
            "generationConfig": generation_config,
        },
    }


def write_jsonl(path, lines: list[dict]) -> None:
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _response_fields(response_json: dict):
    """Get the answer text, token counts and thought summary from a response."""
    text = None
    thought_parts = []
    candidates = response_json.get("candidates") or []
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", []) or []
        for part in parts:
            if part.get("thought"):
                if part.get("text"):
                    thought_parts.append(part["text"])
                continue
            if part.get("text") is not None:
                text = part["text"]
    thought_text = "\n".join(thought_parts) if thought_parts else None
    usage = response_json.get("usageMetadata", {}) or {}
    in_tok = usage.get("promptTokenCount")
    out_tok = (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)
    return text, in_tok, out_tok, thought_text


def parse_result_line(line: str) -> dict:
    obj = json.loads(line)
    key = obj.get("key")
    if obj.get("response") is not None:
        text, in_tok, out_tok, thought_text = _response_fields(obj["response"])
        err = None if text is not None else "empty response"
        return {"key": key, "text": text, "thought_text": thought_text,
                "in_tok": in_tok, "out_tok": out_tok, "error": err}
    err = obj.get("error") or obj.get("status") or "no response"
    return {"key": key, "text": None, "thought_text": None,
            "in_tok": None, "out_tok": None, "error": str(err)}


_TYPE_MAP = {"string": "STRING", "integer": "INTEGER", "number": "NUMBER",
             "boolean": "BOOLEAN", "array": "ARRAY", "object": "OBJECT"}
_KEEP = {"description", "enum", "required"}


def pydantic_to_gemini_schema(json_schema: dict) -> dict:
    """Convert a Pydantic JSON schema into the schema format Gemini expects.

    Gemini doesn't understand $ref and uses "nullable" instead of anyOf with null.
    """
    defs = json_schema.get("$defs", {})

    def resolve(node: dict) -> dict:
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            return resolve(defs.get(name, {}))

        # Optional fields come in as anyOf [T, null]
        if "anyOf" in node:
            variants = [v for v in node["anyOf"] if v.get("type") != "null"]
            nullable = any(v.get("type") == "null" for v in node["anyOf"])
            base = resolve(variants[0]) if variants else {"type": "STRING"}
            if nullable:
                base["nullable"] = True
            for k in _KEEP:
                if k in node:
                    base[k] = node[k]
            return base

        out: dict = {}
        jtype = node.get("type")
        if jtype in _TYPE_MAP:
            out["type"] = _TYPE_MAP[jtype]
        for k in _KEEP:
            if k in node:
                out[k] = node[k]
        if jtype == "object":
            props = node.get("properties", {})
            out["properties"] = {name: resolve(sub) for name, sub in props.items()}
        if jtype == "array" and "items" in node:
            out["items"] = resolve(node["items"])
        return out

    return resolve(json_schema)


def response_schema_dict():
    from shared.extraction_schema import ReportExtraction
    return pydantic_to_gemini_schema(ReportExtraction.model_json_schema())


def upload_jsonl(client, jsonl_path, display_name):
    from google.genai import types
    return client.files.upload(
        file=str(jsonl_path),
        config=types.UploadFileConfig(display_name=display_name, mime_type="jsonl"),
    )


def create_batch(client, model_id, src_file_name, display_name):
    return client.batches.create(
        model=model_id,
        src=src_file_name,
        config={"display_name": display_name},
    )


def get_job(client, job_name):
    return client.batches.get(name=job_name)


def download_bytes(client, file_name):
    return client.files.download(file=file_name)
