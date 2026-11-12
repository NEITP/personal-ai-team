
from pathlib import Path

try:
    from . import state_manager
except ImportError:
    import state_manager


# ==========================================
# TASK MANAGER
# ==========================================

def create_task(task, agents):
    """Create a new workflow."""

    return state_manager.create_workflow(
        original_task=task,
        agents=agents,
    )


def start_task(workflow_id):
    """Start workflow execution."""

    return state_manager.update_workflow_status(
        workflow_id,
        "RUNNING",
    )



def start_agent(workflow_id, agent, task_id=None, result_file=None):
    """Mark an agent as running."""

    update_kwargs = {
        "workflow_id": workflow_id,
        "agent": agent,
        "status": "RUNNING",
        "task_id": task_id,
    }

    # Only pass result_file when explicitly provided.
    if result_file is not None:
        update_kwargs["result_file"] = result_file

    return state_manager.update_agent_status(**update_kwargs)



def complete_agent(
    workflow_id,
    agent,
    task_id=None,
    result_file=None,
    partial=False,
):
    """Mark an agent as successfully completed."""

    status = "PARTIAL" if partial else "SUCCESS"

    return state_manager.update_agent_status(
        workflow_id=workflow_id,
        agent=agent,
        status=status,
        task_id=task_id,
        result_file=result_file,
    )


def fail_agent(
    workflow_id,
    agent,
    error,
    task_id=None,
):
    """Record an agent failure."""

    return state_manager.update_agent_status(
        workflow_id=workflow_id,
        agent=agent,
        status="FAILED",
        task_id=task_id,
        error=str(error),
    )


def skip_agent(workflow_id, agent, reason=None):
    """Mark an agent as skipped."""

    return state_manager.update_agent_status(
        workflow_id=workflow_id,
        agent=agent,
        status="SKIPPED",
        error=reason,
    )


def finish_task(workflow_id, final_report=None):
    """
    Finalize workflow based on agent execution results.

    SUCCESS: all agents succeeded.
    PARTIAL: at least one agent succeeded or was partial,
             but not all agents succeeded.
    FAILED: no agent produced a usable result.
    """

    workflow = state_manager.load_workflow(workflow_id)

    agent_states = [
        item["status"]
        for item in workflow["agents"].values()
    ]

    successful = {"SUCCESS", "PARTIAL"}

    success_count = sum(
        status in successful
        for status in agent_states
    )

    if success_count == 0:
        final_status = "FAILED"
    elif success_count == len(agent_states):
        if all(status == "SUCCESS" for status in agent_states):
            final_status = "SUCCESS"
        else:
            final_status = "PARTIAL"
    else:
        final_status = "PARTIAL"

    if final_report is not None:
        state_manager.set_final_report(
            workflow_id,
            final_report,
        )

    return state_manager.update_workflow_status(
        workflow_id,
        final_status,
    )


def recover_tasks():
    """
    Detect workflows interrupted during execution.

    Running workflows are marked INTERRUPTED.
    Pending workflows are left unchanged.
    """

    workflows = state_manager.get_incomplete_workflows()
    recovered = []

    for workflow in workflows:

        if workflow["status"] != "RUNNING":
            continue

        workflow_id = workflow["workflow_id"]

        state_manager.update_workflow_status(
            workflow_id,
            "INTERRUPTED",
            error="Workflow was interrupted before completion.",
        )

        recovered.append(workflow_id)

    return recovered


def get_task(workflow_id):
    """Retrieve workflow details."""

    return state_manager.load_workflow(workflow_id)


def get_all_tasks():
    """Retrieve all workflows."""

    return state_manager.list_workflows()


# ==========================================
# TEST
# ==========================================

if __name__ == "__main__":

    print("=" * 50)
    print("PERSONAL AI TEAM - TASK MANAGER TEST")
    print("=" * 50)

    # 1. Create workflow
    workflow = create_task(
        task="Task Manager integration test.",
        agents=["codex", "antigravity"],
    )

    workflow_id = workflow["workflow_id"]

    print("\n1. TASK CREATED:", workflow_id)

    # 2. Start workflow
    start_task(workflow_id)

    print("2. TASK STARTED")

    # 3. Simulate Codex execution
    start_agent(
        workflow_id,
        "codex",
        task_id="TASK-TEST-CODEX",
    )

    complete_agent(
        workflow_id,
        "codex",
        task_id="TASK-TEST-CODEX",
        result_file="results/test_codex.json",
    )

    print("3. CODEX COMPLETED")

    # 4. Simulate Antigravity execution
    start_agent(
        workflow_id,
        "antigravity",
        task_id="TASK-TEST-ANTIGRAVITY",
    )

    complete_agent(
        workflow_id,
        "antigravity",
        task_id="TASK-TEST-ANTIGRAVITY",
        result_file="results/test_antigravity.json",
    )

    print("4. ANTIGRAVITY COMPLETED")

    # 5. Finish workflow
    finished = finish_task(workflow_id)

    print("5. TASK FINISHED:", finished["status"])

    # 6. Verify persistence
    reloaded = get_task(workflow_id)

    print("\n6. RELOADED STATUS:", reloaded["status"])

    print("\nTASK MANAGER TEST:",
          "SUCCESS" if reloaded["status"] == "SUCCESS" else "FAILED")

    print("Workflow ID:", workflow_id)
