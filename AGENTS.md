# Personal AI Team

## Main architecture

- Codex CLI is the primary agent and orchestrator.
- Antigravity CLI is a secondary agent.
- Python is used for automation and orchestration.
- Git is used for version control.

## General rules

1. Understand the task before modifying files.
2. Create a plan before complex implementation.
3. Inspect existing code before editing.
4. Do not delete files without user approval.
5. Do not expose API keys, passwords or secrets.
6. Do not modify files outside the project without approval.
7. Run relevant tests after code changes.
8. Explain what was changed and what remains.

## Agent collaboration

- Codex owns task planning and final review.
- Antigravity handles delegated research and coding tasks.
- Every delegated task must have clear inputs and expected outputs.
- Agents must not overwrite each other's work.
- Important decisions must be documented.

## Git policy

- Never force push.
- Never automatically merge branches.
- Review git diff before committing.
- Ask the user before destructive Git operations.
