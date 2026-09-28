"""Gemini client setup and PDF upload."""

from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types


def build_client(api_key: str | None, timeout_s: float | None = None) -> genai.Client:
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Add it to the .env file in the project root.")
    http_options = types.HttpOptions(timeout=int(timeout_s * 1000)) if timeout_s else None
    return genai.Client(api_key=api_key, http_options=http_options)


def upload_pdf(client: genai.Client, pdf_path: Path):
    """Upload a PDF to the Gemini Files API and return the file object."""
    return client.files.upload(file=str(pdf_path))
