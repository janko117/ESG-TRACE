"""Runs stages 1 to 3 of the temporal analysis in one go.

Each stage can still be started on its own.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from shared import config  # noqa: E402
from temporal_analysis import (  # noqa: E402
    stage1_derive_fields,
    stage2_temporal_analysis,
    stage3_justification_extraction,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(config.DB_PATH))
    p.add_argument("--model", default=config.MODEL_ID)
    p.add_argument("--register", default=str(config.REPORT_REGISTER_PATH))
    args = p.parse_args()

    print(f"Database: {args.db}")

    print("\n--- Stage 1: derive fields")
    stage1_derive_fields.run(args.db)

    print("\n--- Stage 2: temporal analysis")
    stage2_temporal_analysis.run(args.db)

    print("\n--- Stage 3: justification extraction")
    stage3_justification_extraction.run(args.db, args.model, args.register)


if __name__ == "__main__":
    main()
