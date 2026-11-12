# Personal AI Team

A personal multi-agent AI workspace focused on low-cost development.

## Agents

| Agent | Responsibility |
|---|---|
| Codex | Main orchestrator and coding |
| Antigravity | Research and delegated coding |
| Ollama | Optional local AI |

## Project structure

- config: Agent and workflow configuration
- orchestrator: Python orchestration engine
- agents: Agent instructions
- skills: Reusable workflows
- memory: Long-term project memory
- projects: Individual software projects
- logs: Execution history
- scripts: Automation scripts

## Principles

- Minimize unnecessary AI requests.
- Reuse existing context.
- Require approval for destructive operations.
- Track changes with Git.
