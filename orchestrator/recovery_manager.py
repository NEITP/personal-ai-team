
from pathlib import Path
import json

try:
    from . import state_manager
    from .validator import validate_result
except ImportError:
    import state_manager
    from validator import validate_result


# ==========================================
# CONFIGURATION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RECOVERABLE_STATUSES = {
    "RUNNING",
    "INTERRUPTED",
    "PARTIAL",
    "FAILED",
}


# ==========================================
# RESULT VALIDATION
# ==========================================

def resolve_project_file(file_path):
    """Resolve a file path and prevent access outside the project."""

    if not file_path:
        return None

    path = Path(file_path)

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    try:
        path = path.resolve()

        if not path.is_relative_to(PROJECT_ROOT.resolve()):
            return None

        return path

    except (OSError, ValueError):
        return None


def load_valid_agent_result(agent_state, agent):
    """
    Load and validate a previously completed agent result.

    Only SUCCESS results with matching task_id and agent
    are eligible for reuse.
    """

    result_file = agent_state.get("result_file")
    task_id = agent_state.get("task_id")

    if not result_file or not task_id:
        return None, "Missing result_file or task_id."

    result_path = resolve_project_file(result_file)

    if result_path is None:
        return None, "Result file path is invalid or outside project."

    if not result_path.is_file():
        return None, "Result file does not exist."

    try:
        with result_path.open("r", encoding="utf-8") as file:
            result = json.load(file)

    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Cannot read result JSON: {exc}"

    if not isinstance(result, dict):
        return None, "Result must be a JSON object."

    valid, errors = validate_result(result)

    if not valid:
        return None, f"Result schema invalid: {errors}"

    if result.get("task_id") != task_id:
        return None, "Result task_id does not match workflow state."

    if result.get("agent") != agent:
        return None, "Result agent does not match workflow state."

    if result.get("status") != "SUCCESS":
        return None, "Only SUCCESS results can be reused."

    return result, None


# ==========================================
# RECOVERY CANDIDATES
# ==========================================

def get_recovery_candidates():
    """Find workflows that are not successfully completed."""

    workflows = state_manager.list_workflows()

    return [
        workflow
        for workflow in workflows
        if workflow.get("status") in RECOVERABLE_STATUSES
    ]


# ==========================================
# FINAL REPORT CHECK
# ==========================================

def check_final_report(workflow):
    """Check whether a registered final report still exists."""

    report_file = workflow.get("final_report")

    if not report_file:
        return False

    report_path = resolve_project_file(report_file)

    if report_path is None:
        return False

    return report_path.is_file()


# ==========================================
# BUILD RECOVERY PLAN
# ==========================================

def build_recovery_plan(workflow_id):
    """
    Inspect a workflow and determine what can be resumed.

    Valid SUCCESS results are reused.
    Valid orphan results from RUNNING agents are reconciled.
    """

    workflow = state_manager.load_workflow(workflow_id)

    if workflow.get("status") == "SUCCESS":
        return {
            "workflow_id": workflow_id,
            "recoverable": False,
            "reason": "Workflow already completed successfully.",
            "completed_agents": [],
            "completed_results": [],
            "pending_agents": [],
            "next_agent": None,
            "needs_synthesis": False,
            "final_report_exists": check_final_report(workflow),
            "warnings": [],
        }

    # A RUNNING workflow found after restart is considered interrupted.
    if workflow.get("status") == "RUNNING":

        state_manager.update_workflow_status(
            workflow_id,
            "INTERRUPTED",
            error="Running workflow detected during recovery scan.",
        )

        # Update local state instead of loading the workflow again.
        workflow["status"] = "INTERRUPTED"

    completed_agents = []
    completed_results = []
    pending_agents = []
    warnings = []

    for agent, agent_state in workflow["agents"].items():

        previous_status = agent_state.get("status")

        # SUCCESS: validate stored result.
        # RUNNING: attempt to recover an orphan result.
        if previous_status in {"SUCCESS", "RUNNING"}:

            result, error = load_valid_agent_result(
                agent_state,
                agent,
            )

            if result is not None:

                if previous_status == "RUNNING":

                    # Reconcile orphan result after process crash.
                    state_manager.update_agent_status(
                        workflow_id=workflow_id,
                        agent=agent,
                        status="SUCCESS",
                        task_id=agent_state["task_id"],
                        result_file=agent_state["result_file"],
                    )

                    # Update local workflow state.
                    agent_state["status"] = "SUCCESS"

                    print(
                        f"[RECOVERY] Recovered orphan result: {agent}"
                    )

                completed_agents.append(agent)
                completed_results.append(result)
                continue

            warnings.append(
                f"{agent}: stored result cannot be reused. {error}"
            )

        else:

            warnings.append(
                f"{agent}: previous status was {previous_status}."
            )

        # No valid result: agent must be retried.
        pending_agents.append(agent)

    final_report_exists = check_final_report(workflow)

    all_agents_completed = (
        len(workflow["agents"]) > 0
        and len(pending_agents) == 0
    )

    needs_synthesis = (
        len(workflow["agents"]) >= 2
        and all_agents_completed
        and not final_report_exists
    )

    next_agent = (
        pending_agents[0]
        if pending_agents
        else None
    )

    return {
        "workflow_id": workflow_id,
        "recoverable": True,
        "workflow_status": workflow["status"],
        "task": workflow["task"],
        "completed_agents": completed_agents,
        "completed_results": completed_results,
        "pending_agents": pending_agents,
        "next_agent": next_agent,
        "needs_synthesis": needs_synthesis,
        "final_report_exists": final_report_exists,
        "warnings": warnings,
    }


# ==========================================
# DISPLAY RECOVERY PLAN
# ==========================================

def print_recovery_plan(plan):

    print("\n" + "=" * 50)
    print("WORKFLOW RECOVERY PLAN")
    print("=" * 50)

    print("Workflow ID:", plan["workflow_id"])
    print("Recoverable:", plan["recoverable"])

    if not plan["recoverable"]:
        print("Reason:", plan["reason"])
        return

    print("Workflow status:", plan["workflow_status"])

    print("\nCompleted agents:")

    if plan["completed_agents"]:
        for agent in plan["completed_agents"]:
            print(f"  [REUSE] {agent}")
    else:
        print("  None")

    print("\nPending agents:")

    if plan["pending_agents"]:
        for agent in plan["pending_agents"]:
            print(f"  [RETRY] {agent}")
    else:
        print("  None")

    print("\nNext agent:", plan["next_agent"])
    print("Needs synthesis:", plan["needs_synthesis"])
    print("Final report exists:", plan["final_report_exists"])

    if plan["warnings"]:
        print("\nWarnings:")

        for warning in plan["warnings"]:
            print("-", warning)


# ==========================================
# TEST
# ==========================================

if __name__ == "__main__":

    print("=" * 50)
    print("PERSONAL AI TEAM - RECOVERY MANAGER TEST")
    print("=" * 50)

    workflow = None
    test_result_file = None

    try:
        # 1. Create a test workflow.
        workflow = state_manager.create_workflow(
            original_task="Recovery Manager integration test.",
            agents=["codex", "antigravity"],
        )

        workflow_id = workflow["workflow_id"]

        print("\n1. TEST WORKFLOW CREATED:", workflow_id)

        state_manager.update_workflow_status(
            workflow_id,
            "RUNNING",
        )

        # 2. Create a valid synthetic Codex result.
        task_id = "TASK-999999999"

        test_result = {
            "schema_version": "1.0",
            "task_id": task_id,
            "agent": "codex",
            "status": "SUCCESS",
            "summary": "Synthetic result for recovery testing.",
            "findings": ["Recovery test finding."],
            "risks": [],
            "recommendations": [],
            "files_changed": [],
            "next_steps": [],
        }

        valid, errors = validate_result(test_result)

        if not valid:
            raise ValueError(
                f"Test result does not match schema: {errors}"
            )

        test_result_file = (
            PROJECT_ROOT
            / "results"
            / f"{task_id}_codex_recovery_test.json"
        )

        test_result_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with test_result_file.open("w", encoding="utf-8") as file:
            json.dump(
                test_result,
                file,
                ensure_ascii=False,
                indent=2,
            )

        # 3. Save Codex as completed.
        state_manager.update_agent_status(
            workflow_id,
            "codex",
            "SUCCESS",
            task_id=task_id,
            result_file=test_result_file,
        )

        print("2. CODEX RESULT CREATED AND SAVED")

        # Antigravity intentionally remains PENDING.

        # 4. Build recovery plan.
        plan = build_recovery_plan(workflow_id)

        print_recovery_plan(plan)

        # 5. Verify expected recovery behavior.
        assert plan["workflow_status"] == "INTERRUPTED"
        assert plan["completed_agents"] == ["codex"]
        assert plan["pending_agents"] == ["antigravity"]
        assert plan["next_agent"] == "antigravity"
        assert len(plan["completed_results"]) == 1

        print("\nRECOVERY MANAGER TEST: SUCCESS")

    finally:
        # Remove only files created by this test.
        if workflow is not None:
            workflow_path = state_manager.get_workflow_path(
                workflow["workflow_id"]
            )

            if workflow_path.exists():
                workflow_path.unlink()

        if test_result_file is not None and test_result_file.exists():
            test_result_file.unlink()

        print("Test artifacts cleaned up.")
