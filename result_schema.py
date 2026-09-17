# ABOUTME: Loads the benchmark run record JSON schema and validates run records against it.
# ABOUTME: The schema file schemas/benchmark_run.schema.json is the source of truth for the record shape.
import json
import os
from typing import Dict, List

import jsonschema

SCHEMA_VERSION = 1

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schemas", "benchmark_run.schema.json")


def load_schema() -> Dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def validate_run_record(record: Dict) -> List[str]:
    """Validate a run record against the schema.

    Returns a list of human-readable error strings. An empty list means the
    record is valid.
    """
    validator = jsonschema.Draft7Validator(load_schema())
    errors = sorted(validator.iter_errors(record), key=lambda e: list(e.absolute_path))
    return [
        f"{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in errors
    ]
