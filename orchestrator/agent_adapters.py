"""Subprocess adapters for the supported agent command line tools."""

import shutil
import subprocess


class AgentAdapterError(RuntimeError):
    """Raised when an agent cannot be executed with its configuration."""


def executable_for(agent, agent_config):
    executable = agent_config.get("command")
    if not executable:
        raise AgentAdapterError(f"No command configured for agent: {agent}")
    return executable


def is_available(agent, agent_config):
    executable = executable_for(agent, agent_config)
    return shutil.which(executable) is not None


def probe_version(agent, agent_config, timeout_seconds=10):
    """Return a normalized CLI version string or a useful adapter error."""
    executable = executable_for(agent, agent_config)
    version_args = agent_config.get("version_args", ["--version"])
    try:
        result = subprocess.run(
            [executable, *version_args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds,
            shell=False, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentAdapterError(f"{agent} version probe timed out.") from exc
    except OSError as exc:
        raise AgentAdapterError(f"Cannot launch {agent} CLI: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no diagnostic returned").strip()
        raise AgentAdapterError(
            f"{agent} version probe exited {result.returncode}: {detail[:500]}"
        )
    version = (result.stdout or result.stderr).strip()
    if not version:
        raise AgentAdapterError(f"{agent} returned an empty version response.")
    return version.splitlines()[0][:300]


def _assert_ollama_model_installed(executable, model):
    """Avoid Ollama's implicit model download when a model is missing."""
    try:
        result = subprocess.run(
            [executable, "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentAdapterError(
            f"Could not check local Ollama models: {exc}"
        ) from exc

    if result.returncode != 0:
        message = result.stderr.strip() or "ollama list failed"
        raise AgentAdapterError(message)

    installed = {
        line.split()[0]
        for line in result.stdout.splitlines()[1:]
        if line.split()
    }
    expected = model if ":" in model else f"{model}:latest"
    if expected not in installed and model not in installed:
        raise AgentAdapterError(
            f"Ollama model '{model}' is not installed locally. "
            f"Run 'ollama pull {model}' before using this agent."
        )


def build_command(agent, prompt, agent_config, project_root):
    """Build a shell-free command and return its optional stdin payload."""
    executable = executable_for(agent, agent_config)

    if agent == "codex":
        return [
            executable,
            "exec",
            "--sandbox", "read-only",
            "-C", str(project_root),
            "-",
        ], prompt

    if agent == "antigravity":
        return [
            executable,
            "--mode", "plan",
            "--sandbox",
            f"--print={prompt}",
        ], None

    if agent == "ollama":
        model = agent_config.get("model")
        if not model:
            raise AgentAdapterError(
                "Ollama requires a model in config/agents.yaml "
                "(for example: model: llama3.2)."
            )
        return [executable, "run", model], prompt

    raise AgentAdapterError(f"No adapter is registered for agent: {agent}")


def run(agent, prompt, agent_config, project_root, timeout_seconds):
    """Run an agent and return subprocess.CompletedProcess."""
    command, stdin = build_command(
        agent,
        prompt,
        agent_config,
        project_root,
    )
    if agent == "ollama":
        _assert_ollama_model_installed(
            executable_for(agent, agent_config),
            agent_config["model"],
        )
    try:
        return subprocess.run(
            command, cwd=project_root, input=stdin, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=timeout_seconds, shell=False, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentAdapterError(f"{agent} CLI timed out after {timeout_seconds}s.") from exc
    except OSError as exc:
        raise AgentAdapterError(f"Cannot launch {agent} CLI: {exc}") from exc


def run_codex(prompt, agent_config, project_root, timeout_seconds):
    """Run Codex for Markdown synthesis through the same adapter path."""
    return run(
        "codex",
        prompt,
        agent_config,
        project_root,
        timeout_seconds,
    )
