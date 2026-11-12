
import json
from pathlib import Path

from jsonschema import Draft202012Validator


# ==========================================
# PATH CONFIGURATION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = PROJECT_ROOT / "schemas"

TASK_SCHEMA_FILE = SCHEMA_DIR / "task_spec.schema.json"
RESULT_SCHEMA_FILE = SCHEMA_DIR / "agent_result.schema.json"


# ==========================================
# SCHEMA LOADING
# ==========================================

def load_schema(schema_file: Path) -> dict:
    """Load and validate a JSON Schema file."""

    if not schema_file.exists():
        raise FileNotFoundError(
            f"Schema file not found: {schema_file}"
        )

    with schema_file.open("r", encoding="utf-8") as file:
        schema = json.load(file)

    Draft202012Validator.check_schema(schema)

    return schema


# ==========================================
# DATA VALIDATION
# ==========================================

def validate_data(data: dict, schema_file: Path) -> tuple[bool, list[str]]:
    """
    Validate a Python dictionary against a JSON Schema.

    Returns:
        (True, []) if valid.
        (False, [error messages]) if invalid.
    """

    try:
        schema = load_schema(schema_file)
        validator = Draft202012Validator(schema)

        errors = sorted(
            validator.iter_errors(data),
            key=lambda error: list(error.absolute_path),
        )

        if not errors:
            return True, []

        messages = []

        for error in errors:
            location = ".".join(
                str(part) for part in error.absolute_path
            ) or "root"

            messages.append(
                f"{location}: {error.message}"
            )

        return False, messages

    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        return False, [str(exc)]


# ==========================================
# PUBLIC VALIDATION FUNCTIONS
# ==========================================

def validate_task(task: dict) -> tuple[bool, list[str]]:
    """Validate a task specification."""

    return validate_data(task, TASK_SCHEMA_FILE)


def validate_result(result: dict) -> tuple[bool, list[str]]:
    """Validate an agent result."""

    return validate_data(result, RESULT_SCHEMA_FILE)


# ==========================================
# MANUAL TEST
# ==========================================

if __name__ == "__main__":
    print("=" * 50)
    print("PERSONAL AI TEAM - VALIDATOR TEST")
    print("=" * 50)

    sample_task = {
        "schema_version": "1.0",
        "task_id": "TASK-001",
        "assigned_to": "codex",
        "task_type": "analysis",
        "objective": "Analyze project architecture",
        "context": {
            "summary": "Review the current orchestrator.",
            "files": [
                "orchestrator/main.py"
            ]
        },
        "constraints": [
            "Read-only",
            "Do not modify files"
        ],
        "acceptance_criteria": [
            "Identify at least three improvements"
        ],
        "output_format": "markdown"
    }

    valid, errors = validate_task(sample_task)

    if valid:
        print("\nTASK VALIDATION: SUCCESS")
    else:
        print("\nTASK VALIDATION: FAILED")
        for error in errors:
            print("-", error)

    print("\n" + "=" * 50)
