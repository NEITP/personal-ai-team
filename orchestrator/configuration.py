"""Load and normalize the workspace's YAML configuration."""

from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"

AGENT_ALIASES = {
    "orchestrator": "codex",
    "researcher": "antigravity",
    "local": "ollama",
}


def _read_yaml(filename):
    path = CONFIG_DIR / filename
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration must be a YAML mapping: {path}")
    return data


def load_configuration():
    """Return normalized agent, route, and policy configuration."""
    agents_data = _read_yaml("agents.yaml")
    routing_data = _read_yaml("routing.yaml")
    policies = _read_yaml("policies.yaml")

    agents = {}
    for key, entry in agents_data.get("agents", {}).items():
        if not isinstance(entry, dict):
            raise ValueError(f"Agent configuration must be a mapping: {key}")
        name = AGENT_ALIASES.get(key, key)
        if entry.get("enabled", False):
            agents[name] = {
                **entry,
                "name": name,
                "command": entry.get("command", name),
            }

    routes = routing_data.get("routing", {})
    if not agents:
        raise ValueError("At least one configured agent must be enabled.")
    if not routes:
        raise ValueError("At least one task routing rule is required.")

    execution = routing_data.get("execution", {})
    policy_execution = policies.get("execution", {})
    settings = agents_data.get("settings", {})
    logging = policies.get("logging", {})
    context = policies.get("context", {})
    security = policies.get("security", {})
    max_retries = execution.get("max_retries", 0)
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ValueError("max_retries values must be non-negative integers.")
    execution_mode = execution.get("mode", "sequential")
    if execution_mode not in {"sequential", "parallel"}:
        raise ValueError("execution.mode must be 'sequential' or 'parallel'.")
    allow_parallel = execution.get("allow_parallel", False)
    if not isinstance(allow_parallel, bool):
        raise ValueError("execution.allow_parallel must be a boolean.")
    if execution_mode == "parallel" and not allow_parallel:
        raise ValueError(
            "execution.mode is parallel but execution.allow_parallel is false."
        )
    for route_name, route in routes.items():
        if not isinstance(route, dict):
            raise ValueError(f"Route must be a mapping: {route_name}")
        route_mode = route.get("execution", "sequential")
        if route_mode not in {"sequential", "parallel", "either"}:
            raise ValueError(
                f"Route {route_name} execution must be sequential, parallel, or either."
            )
        has_reviewer = (
            route.get("require_review")
            or route.get("reviewer") not in (None, "none")
        )
        if has_reviewer and route_mode == "parallel":
            raise ValueError(
                f"Route {route_name} requires review and cannot run in parallel."
            )
    if any(
        route.get("execution") == "parallel" for route in routes.values()
    ) and not allow_parallel:
        raise ValueError(
            "A route requires parallel execution while execution.allow_parallel is false."
        )
    max_agents = execution.get("max_agents_per_task", 2)
    if isinstance(max_agents, bool) or not isinstance(max_agents, int) or max_agents < 1:
        raise ValueError("max_agents_per_task must be a positive integer.")

    context_patterns = context.get(
        "blocked_file_patterns",
        [
            ".env", ".env.*", "*credential*", "*secret*",
            "id_rsa*", "id_ed25519*", "*.pem", "*.key",
        ],
    )
    env_patterns = {".env", ".env.*"}
    blocked_patterns = [
        pattern
        for pattern in context_patterns
        if (
            pattern in env_patterns
            and security.get("protect_env_files", True)
        ) or (
            pattern not in env_patterns
            and security.get("protect_secrets", True)
        )
    ]
    return {
        "agents": agents,
        "routes": routes,
        "max_agents": max_agents,
        "timeout_seconds": policy_execution.get("timeout_seconds", 900),
        "preserve_logs": policy_execution.get("preserve_logs", True),
        "parallel_execution": execution_mode == "parallel",
        "allow_parallel_execution": allow_parallel,
        "max_retries": max_retries,
        "logging": {
            "include_prompt": logging.get("include_prompt", False),
            "include_raw_output": logging.get("include_raw_output", False),
            "include_diagnostics": logging.get("include_diagnostics", False),
            "include_structured_result": logging.get(
                "include_structured_result",
                False,
            ),
        },
        "context": {
            "show_loaded_files": context.get("show_loaded_files", True),
            "max_file_size_bytes": context.get("max_file_size_bytes", 60_000),
            "max_total_characters": context.get(
                "max_total_characters",
                100_000,
            ),
            "blocked_file_patterns": blocked_patterns,
            "restrict_workspace": security.get("restrict_workspace", True),
            "scan_secret_content": security.get("scan_secret_content", True),
        },
    }


def agents_for_route(configuration, route_name):
    """Resolve the primary and optional reviewer/secondary for a route."""
    route = configuration["routes"].get(route_name)
    if route is None:
        raise ValueError(f"Unknown task type: {route_name}")

    selected = [route.get("primary")]
    reviewer = route.get("reviewer")
    secondary = route.get("secondary")
    if reviewer not in (None, "none"):
        selected.append(reviewer)
    elif route.get("require_review") and secondary not in (None, "none"):
        selected.append(secondary)
    elif secondary not in (None, "none"):
        selected.append(route["secondary"])

    normalized = []
    for agent in selected:
        if agent in (None, "none"):
            continue
        agent = AGENT_ALIASES.get(agent, agent)
        if agent not in configuration["agents"]:
            raise ValueError(
                f"Route references disabled or unknown agent: {agent}"
            )
        if agent not in normalized:
            normalized.append(agent)

    if not normalized or len(normalized) > configuration["max_agents"]:
        raise ValueError(
            f"Route {route_name} selects {len(normalized)} agents; "
            f"configured maximum is {configuration['max_agents']}."
        )
    return normalized


def route_execution(configuration, route_name):
    """Return a route's execution rule: sequential, parallel, or either."""
    route = configuration["routes"].get(route_name)
    if route is None:
        raise ValueError(f"Unknown task type: {route_name}")
    mode = route.get("execution", "sequential")
    if mode not in {"sequential", "parallel", "either"}:
        raise ValueError(
            f"Route {route_name} execution must be sequential, parallel, or either."
        )
    if (route.get("require_review") or route.get("reviewer") not in (None, "none")) and mode == "parallel":
        raise ValueError(
            f"Route {route_name} requires review and cannot run in parallel."
        )
    return mode
