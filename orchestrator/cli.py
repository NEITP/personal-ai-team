"""Command line interface for starting and inspecting workflows."""

import argparse
import json
import sys


def build_cli_parser(configuration):
    parser = argparse.ArgumentParser(
        prog="personal-ai-team",
        description="Run and manage Personal AI Team workflows.",
    )
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("doctor", help="Check configured agent CLIs and versions")

    run_parser = commands.add_parser("run", help="Run a task workflow")
    run_parser.add_argument("task", nargs="+", help="Task prompt")
    run_mode = run_parser.add_mutually_exclusive_group()
    run_mode.add_argument(
        "--route",
        choices=sorted(configuration["routes"]),
        help="Choose a configured task route",
    )
    run_mode.add_argument(
        "--agent",
        choices=(
            list(configuration["agents"])
            + (["both"] if all(
                agent in configuration["agents"]
                for agent in ("codex", "antigravity")
            ) else [])
        ),
        help="Run one agent or both configured primary agents",
    )
    parallel_mode = run_parser.add_mutually_exclusive_group()
    parallel_mode.add_argument(
        "--parallel",
        dest="parallel_execution",
        action="store_true",
        help="Run selected agents concurrently",
    )
    parallel_mode.add_argument(
        "--sequential",
        dest="parallel_execution",
        action="store_false",
        help="Run selected agents in sequence",
    )
    run_parser.set_defaults(parallel_execution=None)

    status_parser = commands.add_parser(
        "status",
        help="Show one workflow or recent workflow statuses",
    )
    status_parser.add_argument("workflow_id", nargs="?")
    status_parser.add_argument("--limit", type=int, default=10)
    status_parser.add_argument(
        "--show-task", action="store_true",
        help="Display stored task text (may contain sensitive data)",
    )

    resume_parser = commands.add_parser(
        "resume",
        help="Resume a workflow; omit its ID when only one is recoverable",
    )
    resume_parser.add_argument("workflow_id", nargs="?")

    prune_parser = commands.add_parser(
        "prune",
        help="Preview or remove old completed workflow data",
    )
    prune_parser.add_argument("--older-than-days", type=int, default=30)
    prune_parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the previewed workflow state and unshared artifacts",
    )
    return parser


def show_workflow_status(runtime, workflow_id=None, limit=10, show_task=False):
    """Print concise state and timing information for saved workflows."""
    try:
        if workflow_id:
            workflows = [runtime.task_manager.get_task(workflow_id)]
        else:
            if limit < 1:
                print("[STATUS] --limit must be at least 1.")
                return False
            workflows = runtime.task_manager.get_all_tasks()[:limit]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[STATUS] Cannot read workflow state: {exc}")
        return False

    if not workflows:
        print("No workflows found.")
        return True

    for index, workflow in enumerate(workflows):
        if index:
            print()
        print(f"Workflow: {workflow.get('workflow_id', '(unknown)')}")
        print(f"Status: {workflow.get('status', 'UNKNOWN')}")
        task_text = workflow.get("task", "") if show_task else "[hidden; use --show-task to display]"
        print(f"Task: {task_text}")
        for agent, state in workflow.get("agents", {}).items():
            detail = f"  {agent}: {state.get('status', 'UNKNOWN')}"
            if state.get("error"):
                detail += f" | {state['error']}"
            print(detail)
            metrics = state.get("metrics", {})
            if metrics:
                last_duration = metrics.get("duration_seconds")
                total_duration = metrics.get("total_duration_seconds", 0)
                duration_text = (
                    f"last {last_duration:.2f}s, total {total_duration:.2f}s"
                    if last_duration is not None
                    else f"total {total_duration:.2f}s"
                )
                cost = metrics.get("cost_usd")
                cost_text = f"${cost:.4f}" if cost is not None else "unknown"
                print(
                    f"    attempts: {metrics.get('attempts', 0)} | "
                    f"duration: {duration_text} | cost: {cost_text}"
                )
        if workflow.get("final_report"):
            print(f"Final report: {workflow['final_report']}")
        if workflow.get("error"):
            print(f"Workflow error: {workflow['error']}")
        synthesis = workflow.get("synthesis", {})
        synthesis_duration = synthesis.get("duration_seconds")
        if synthesis_duration is not None:
            cost = synthesis.get("cost_usd")
            cost_text = f"${cost:.4f}" if cost is not None else "unknown"
            print(f"Synthesis: {synthesis_duration:.2f}s | cost: {cost_text}")
    return True


def _select_resume_id(runtime, workflow_id=None):
    if workflow_id:
        return workflow_id
    candidates = runtime.recovery_manager.get_recovery_candidates()
    if len(candidates) == 1:
        return candidates[0]["workflow_id"]
    if not candidates:
        print("No recoverable workflows found.")
    else:
        print("More than one workflow can be resumed. Choose an ID:")
        for workflow in candidates:
            print(f"- {workflow['workflow_id']} ({workflow['status']})")
    return None


def _select_agents(runtime, cli_args):
    if cli_args.route:
        return runtime.agents_for_route(
            runtime.CONFIGURATION,
            cli_args.route,
        )
    if cli_args.agent == "both":
        return ["codex", "antigravity"]
    if cli_args.agent:
        return [cli_args.agent]
    return runtime.agents_for_route(
        runtime.CONFIGURATION,
        "simple_questions",
    )


def _run_cli_command(runtime, cli_args):
    if cli_args.command == "doctor":
        failed = False
        for agent, agent_config in runtime.CONFIGURATION["agents"].items():
            try:
                if not runtime.agent_adapters.is_available(agent, agent_config):
                    raise runtime.agent_adapters.AgentAdapterError(
                        f"CLI '{agent_config.get('command', agent)}' not found on PATH."
                    )
                version = runtime.agent_adapters.probe_version(agent, agent_config)
                print(f"[OK] {agent}: {version}")
            except runtime.agent_adapters.AgentAdapterError as exc:
                print(f"[ERROR] {agent}: {exc}")
                failed = True
        if len(runtime.CONFIGURATION["agents"]) > 1 and "codex" not in runtime.CONFIGURATION["agents"]:
            print("[ERROR] Codex must be enabled to synthesize multi-agent results.")
            failed = True
        return 1 if failed else 0

    if cli_args.command == "status":
        return 0 if show_workflow_status(
            runtime,
            cli_args.workflow_id,
            cli_args.limit,
            cli_args.show_task,
        ) else 1

    if cli_args.command == "resume":
        workflow_id = _select_resume_id(runtime, cli_args.workflow_id)
        if not workflow_id:
            return 0
        return runtime.resume_workflow(workflow_id) or 0

    if cli_args.command == "prune":
        try:
            report = runtime.prune_workflows(
                older_than_days=cli_args.older_than_days,
                apply=cli_args.apply,
            )
        except ValueError as exc:
            print(f"[PRUNE] {exc}")
            return 2
        if not report["workflows"]:
            print("No completed workflows match the retention cutoff.")
            return 0
        for item in report["workflows"]:
            print(f"Workflow: {item['workflow_id']}")
            print(f"  State: {item['workflow_file']}")
            for artifact in sorted(item["artifacts"]):
                print(f"  Artifact: {artifact}")
        if not cli_args.apply:
            print("Preview only. Add --apply to delete these files.")
            return 0
        print(f"Deleted files: {len(report['deleted'])}")
        for error in report["errors"]:
            print(f"[PRUNE] Could not delete: {error}")
        return 1 if report["errors"] else 0

    prompt = " ".join(cli_args.task).strip()
    try:
        selected_agents = _select_agents(runtime, cli_args)
    except ValueError as exc:
        print(f"[CONFIG] {exc}")
        return 2

    parallel = runtime.CONFIGURATION["parallel_execution"]
    if cli_args.route:
        try:
            route_mode = runtime.route_execution(
                runtime.CONFIGURATION,
                cli_args.route,
            )
        except ValueError as exc:
            print(f"[ROUTE] {exc}")
            return 2
        if route_mode == "sequential" and cli_args.parallel_execution is True:
            print(f"[ROUTE] {cli_args.route} is configured for sequential execution.")
            return 2
        if route_mode == "parallel" and cli_args.parallel_execution is False:
            print(f"[ROUTE] {cli_args.route} is configured for parallel execution.")
            return 2
        if route_mode == "parallel":
            parallel = True
        elif route_mode == "sequential":
            parallel = False
        elif cli_args.parallel_execution is not None:
            parallel = cli_args.parallel_execution
    elif cli_args.parallel_execution is not None:
        parallel = cli_args.parallel_execution

    if parallel and not runtime.CONFIGURATION["allow_parallel_execution"]:
        print("[POLICY] Parallel execution is disabled by policy.")
        return 2
    return runtime.run_workflow(prompt, selected_agents, parallel=parallel)


def _run_interactive(runtime):
    print("=" * 50)
    print("PERSONAL AI TEAM - ORCHESTRATOR")
    print("=" * 50)
    print("\nSelect operation:")
    menu_labels = {
        "1": "Codex",
        "2": "Antigravity",
        "3": "Both (sequential + synthesis)",
        "6": "Ollama (local model)",
    }
    for menu_key, label in menu_labels.items():
        if menu_key in runtime.AGENTS:
            print(f"{menu_key}. {label}")
    print("4. Resume interrupted workflow")
    print("5. Route by task type (from config/routing.yaml)")

    choice = input("\nYour choice: ").strip()
    if choice == "4":
        workflow_id = runtime.select_recovery_workflow()
        if workflow_id:
            return runtime.resume_workflow(workflow_id)
        return 0

    route_execution_mode = "either"
    if choice == "5":
        route_names = list(runtime.CONFIGURATION["routes"])
        print("\nTask types:")
        for index, name in enumerate(route_names, start=1):
            print(f"{index}. {name.replace('_', ' ').title()}")
        route_choice = input("Choose task type: ").strip()
        try:
            route_index = int(route_choice) - 1
            if route_index < 0 or route_index >= len(route_names):
                raise IndexError("task type selection is out of range")
            route_name = route_names[route_index]
            selected_agents = runtime.agents_for_route(
                runtime.CONFIGURATION,
                route_name,
            )
            route = runtime.CONFIGURATION["routes"][route_name]
            route_execution_mode = runtime.route_execution(
                runtime.CONFIGURATION,
                route_name,
            )
        except (ValueError, IndexError) as exc:
            print(f"Invalid or unavailable route: {exc}")
            return 2
    elif choice in runtime.AGENTS:
        selected_agents = runtime.AGENTS[choice]
    else:
        print("Invalid choice.")
        return 2

    if len(selected_agents) > runtime.CONFIGURATION["max_agents"]:
        print(
            "Selected workflow exceeds configured maximum of "
            f"{runtime.CONFIGURATION['max_agents']} agent(s)."
        )
        return 2

    parallel = False
    if route_execution_mode == "sequential":
        print("This route is configured for sequential execution.")
    elif route_execution_mode == "parallel":
        parallel = True
    elif len(selected_agents) > 1 and runtime.CONFIGURATION["allow_parallel_execution"]:
        default_parallel = runtime.CONFIGURATION["parallel_execution"]
        answer = input(
            "Run agents concurrently? "
            f"{'[Y/n]' if default_parallel else '[y/N]'}: "
        ).strip().lower()
        parallel = (
            answer not in {"n", "no"}
            if default_parallel
            else answer in {"y", "yes"}
        )

    prompt = runtime.read_multiline_prompt()
    if not prompt:
        print("Task cannot be empty.")
        return 2
    print("\nSelected agents:", ", ".join(selected_agents))
    return runtime.run_workflow(prompt, selected_agents, parallel=parallel)


def main(argv=None, runtime=None):
    """Entry point; runtime injection keeps CLI behavior easy to test."""
    if runtime is None:
        try:
            from . import main as runtime
        except ImportError:
            import main as runtime

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass

    argv = sys.argv[1:] if argv is None else argv
    parser = build_cli_parser(runtime.CONFIGURATION)
    cli_args = parser.parse_args(argv) if argv else None
    if cli_args and cli_args.command:
        return _run_cli_command(runtime, cli_args)
    if cli_args and cli_args.command is None and argv:
        parser.error(f"unknown command: {argv[0]}")
    return _run_interactive(runtime)
