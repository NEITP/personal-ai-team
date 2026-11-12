
from pathlib import Path
from datetime import datetime
import json
import uuid


# ==========================================
# CONFIGURATION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

STATE_DIR = PROJECT_ROOT / "state"
WORKFLOW_DIR = STATE_DIR / "workflows"

WORKFLOW_STATUSES = {
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "PARTIAL",
    "FAILED",
    "INTERRUPTED",
}

AGENT_STATUSES = {
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "PARTIAL",
    "FAILED",
    "SKIPPED",
}


# ==========================================
# HELPERS
# ==========================================

def get_timestamp():
    return datetime.now().astimezone().isoformat()


def generate_workflow_id():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"WF-{timestamp}"


def get_workflow_path(workflow_id):
    if not workflow_id.startswith("WF-"):
        raise ValueError("Invalid workflow ID.")

    if any(char in workflow_id for char in ("/", "\\", "..")):
        raise ValueError("Invalid workflow ID.")

    return WORKFLOW_DIR / f"{workflow_id}.json"


def save_workflow(workflow):
    """Save workflow state atomically."""

    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

    workflow_id = workflow["workflow_id"]
    workflow_path = get_workflow_path(workflow_id)

    temp_path = workflow_path.with_suffix(".json.tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(
            workflow,
            file,
            ensure_ascii=False,
            indent=2,
        )

    temp_path.replace(workflow_path)

    return workflow_path


# ==========================================
# WORKFLOW CREATION
# ==========================================

def create_workflow(original_task, agents):
    """Create a new workflow and initialize agent states."""

    if not isinstance(original_task, str) or not original_task.strip():
        raise ValueError("Task cannot be empty.")

    if not agents:
        raise ValueError("At least one agent is required.")

    if len(agents) > 2:
        raise ValueError("Maximum 2 agents per workflow.")

    if len(set(agents)) != len(agents):
        raise ValueError("Duplicate agents are not allowed.")

    supported_agents = {"codex", "antigravity", "ollama"}

    for agent in agents:
        if agent not in supported_agents:
            raise ValueError(f"Unsupported agent: {agent}")

    now = get_timestamp()
    workflow_id = generate_workflow_id()

    workflow = {
        "schema_version": "1.0",
        "workflow_id": workflow_id,
        "task": original_task.strip(),
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
        "agents": {
            agent: {
                "status": "PENDING",
                "task_id": None,
                "result_file": None,
                "started_at": None,
                "completed_at": None,
                "error": None,
            }
            for agent in agents
        },
        "final_report": None,
        "error": None,
    }

    save_workflow(workflow)

    return workflow


# ==========================================
# WORKFLOW RETRIEVAL
# ==========================================

def load_workflow(workflow_id):
    """Load a workflow from persistent storage."""

    workflow_path = get_workflow_path(workflow_id)

    if not workflow_path.is_file():
        raise FileNotFoundError(
            f"Workflow not found: {workflow_id}"
        )

    with workflow_path.open("r", encoding="utf-8") as file:
        workflow = json.load(file)

    if workflow.get("workflow_id") != workflow_id:
        raise ValueError("Workflow ID mismatch.")

    return workflow


def list_workflows():
    """Return all stored workflows."""

    if not WORKFLOW_DIR.exists():
        return []

    workflows = []

    for workflow_path in sorted(
        WORKFLOW_DIR.glob("WF-*.json"),
        reverse=True,
    ):
        try:
            with workflow_path.open("r", encoding="utf-8") as file:
                workflows.append(json.load(file))
        except (OSError, json.JSONDecodeError):
            continue

    return workflows


# ==========================================
# WORKFLOW STATUS
# ==========================================

def update_workflow_status(workflow_id, status, error=None):
    """Update the overall workflow status."""

    if status not in WORKFLOW_STATUSES:
        raise ValueError(f"Invalid workflow status: {status}")

    workflow = load_workflow(workflow_id)

    workflow["status"] = status
    workflow["updated_at"] = get_timestamp()
    workflow["error"] = error

    save_workflow(workflow)

    return workflow


# ==========================================
# AGENT STATUS
# ==========================================

def update_agent_status(
    workflow_id,
    agent,
    status,
    task_id=None,
    result_file=None,
    error=None,
):
    """Update one agent's execution state."""

    if status not in AGENT_STATUSES:
        raise ValueError(f"Invalid agent status: {status}")

    workflow = load_workflow(workflow_id)

    if agent not in workflow["agents"]:
        raise ValueError(
            f"Agent is not registered in workflow: {agent}"
        )

    agent_state = workflow["agents"][agent]
    now = get_timestamp()

    agent_state["status"] = status

    if task_id is not None:
        agent_state["task_id"] = task_id

    if result_file is not None:
        agent_state["result_file"] = str(result_file)

    if status == "RUNNING":
        agent_state["started_at"] = now
        agent_state["completed_at"] = None

    if status in {"SUCCESS", "PARTIAL", "FAILED", "SKIPPED"}:
        agent_state["completed_at"] = now

    agent_state["error"] = error

    workflow["updated_at"] = now

    save_workflow(workflow)

    return workflow


# ==========================================
# FINAL REPORT
# ==========================================

def set_final_report(workflow_id, report_file):
    """Register the final report generated by the synthesizer."""

    workflow = load_workflow(workflow_id)

    report_path = Path(report_file)

    if not report_path.is_absolute():
        report_path = PROJECT_ROOT / report_path

    if not report_path.is_file():
        raise FileNotFoundError(
            f"Final report does not exist: {report_path}"
        )

    workflow["final_report"] = str(
        report_path.relative_to(PROJECT_ROOT)
    )

    workflow["updated_at"] = get_timestamp()

    save_workflow(workflow)

    return workflow


def clear_final_report(workflow_id):
    """Clear the registered final report from a workflow."""

    workflow = load_workflow(workflow_id)

    workflow["final_report"] = None
    workflow["updated_at"] = get_timestamp()

    save_workflow(workflow)

    return workflow


# ==========================================
# RECOVERY
# ==========================================

def get_incomplete_workflows():
    """Find workflows that may need recovery."""

    terminal_statuses = {
        "SUCCESS",
        "FAILED",
    }

    return [
        workflow
        for workflow in list_workflows()
        if workflow.get("status") not in terminal_statuses
    ]


# ==========================================
# TEST
# ==========================================

if __name__ == "__main__":

    print("=" * 50)
    print("PERSONAL AI TEAM - STATE MANAGER TEST")
    print("=" * 50)

    workflow = create_workflow(
        original_task="Test workflow state management.",
        agents=["codex", "antigravity"],
    )

    workflow_id = workflow["workflow_id"]

    print("\nWORKFLOW CREATED")
    print("Workflow ID:", workflow_id)
    print("Status:", workflow["status"])

    update_workflow_status(
        workflow_id,
        "RUNNING",
    )

    update_agent_status(
        workflow_id,
        "codex",
        "RUNNING",
        task_id="TASK-TEST-001",
    )

    update_agent_status(
        workflow_id,
        "codex",
        "SUCCESS",
        task_id="TASK-TEST-001",
        result_file="results/TASK-TEST-001_codex.json",
    )

    loaded_workflow = load_workflow(workflow_id)

    print("\nWORKFLOW RELOADED")
    print(
        json.dumps(
            loaded_workflow,
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\nINCOMPLETE WORKFLOWS")
    print(len(get_incomplete_workflows()))

    print("\nSTATE MANAGER TEST: SUCCESS")
    print("State directory:", WORKFLOW_DIR)
