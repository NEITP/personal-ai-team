"""Safe preview and explicit pruning of completed workflow data."""

from datetime import datetime, timedelta
from pathlib import Path

try:
    from . import state_manager
except ImportError:
    import state_manager


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERMINAL_STATUSES = {"SUCCESS", "PARTIAL", "FAILED"}


def _resolve_owned_file(value):
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        resolved = path.resolve()
        if resolved.is_relative_to(PROJECT_ROOT.resolve()) and resolved.is_file():
            return resolved
    except (OSError, ValueError):
        pass
    return None


def plan_prune(older_than_days=30, now=None):
    """Return completed workflows and owned artifacts older than the cutoff."""
    if isinstance(older_than_days, bool) or not isinstance(older_than_days, int):
        raise ValueError("older_than_days must be an integer.")
    if older_than_days < 0:
        raise ValueError("older_than_days cannot be negative.")

    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        raise ValueError("now must include timezone information.")
    cutoff = now - timedelta(days=older_than_days)
    workflows = state_manager.list_workflows()
    prunable = []

    for workflow in workflows:
        if workflow.get("status") not in TERMINAL_STATUSES:
            continue
        try:
            updated = datetime.fromisoformat(workflow["updated_at"])
            if updated.tzinfo is None or updated >= cutoff:
                continue
        except (KeyError, TypeError, ValueError):
            continue

        try:
            with state_manager.workflow_lease(workflow["workflow_id"], timeout=0):
                pass
        except state_manager.WorkflowBusyError:
            continue

        workflow_id = workflow.get("workflow_id")
        try:
            workflow_file = state_manager.get_workflow_path(workflow_id).resolve()
            if not workflow_file.is_relative_to(PROJECT_ROOT.resolve()):
                continue
        except (OSError, ValueError, TypeError):
            continue

        artifacts = set()
        for agent_state in workflow.get("agents", {}).values():
            artifact = _resolve_owned_file(agent_state.get("result_file"))
            if artifact:
                artifacts.add(artifact)
        report = _resolve_owned_file(workflow.get("final_report"))
        if report:
            artifacts.add(report)

        prunable.append({
            "workflow_id": workflow_id,
            "workflow_file": workflow_file,
            "artifacts": artifacts,
        })

    # Preserve artifacts that are still referenced by a workflow outside the
    # prune set, even if an old record points to the same file.
    prunable_ids = {item["workflow_id"] for item in prunable}
    retained_references = set()
    for workflow in workflows:
        if workflow.get("workflow_id") in prunable_ids:
            continue
        for agent_state in workflow.get("agents", {}).values():
            artifact = _resolve_owned_file(agent_state.get("result_file"))
            if artifact:
                retained_references.add(artifact)
        report = _resolve_owned_file(workflow.get("final_report"))
        if report:
            retained_references.add(report)

    for item in prunable:
        item["artifacts"] -= retained_references
    return prunable


def prune_completed_workflows(older_than_days=30, apply=False):
    """Preview pruning by default; unlink only when apply=True."""
    plan = plan_prune(older_than_days)
    if not apply:
        return {
            "applied": False,
            "workflows": plan,
            "deleted": [],
            "errors": [],
        }

    deleted = []
    errors = []
    for item in plan:
        try:
            with state_manager.workflow_lease(item["workflow_id"], timeout=0):
                # Remove only paths still inside the project and still present.
                targets = [item["workflow_file"], *sorted(item["artifacts"])]
                for target in targets:
                    try:
                        target.resolve().relative_to(PROJECT_ROOT.resolve())
                        if target.is_file():
                            target.unlink()
                            deleted.append(str(target))
                    except (OSError, ValueError) as exc:
                        errors.append(f"{target}: {exc}")
        except state_manager.WorkflowBusyError as exc:
            errors.append(str(exc))

    return {
        "applied": True,
        "workflows": plan,
        "deleted": deleted,
        "errors": errors,
    }
