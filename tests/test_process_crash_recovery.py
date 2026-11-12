
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_DIR = PROJECT_ROOT / "orchestrator"

sys.path.insert(0, str(ORCHESTRATOR_DIR))

import state_manager
import recovery_manager


class TestProcessCrashRecovery(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.marker = Path(self.temp_dir.name) / "workflow_id.txt"
        self.created_workflows = []
        self.created_results = []

    def tearDown(self):
        for workflow_id in self.created_workflows:
            path = state_manager.get_workflow_path(workflow_id)
            if path.exists():
                path.unlink()

        for path in self.created_results:
            if path.exists():
                path.unlink()

        self.temp_dir.cleanup()

    def run_crashed_process(
        self,
        task_id,
        complete_codex,
        register_attempt=False,
    ):
        marker = repr(str(self.marker))
        complete = repr(complete_codex)
        register = repr(register_attempt)

        child_code = f'''
import json
import os
from pathlib import Path

import state_manager
import task_manager

workflow = task_manager.create_task(
    task="Real process crash recovery test.",
    agents=["codex", "antigravity"],
)

workflow_id = workflow["workflow_id"]
Path({marker}).write_text(workflow_id, encoding="utf-8")

task_manager.start_task(workflow_id)

task_manager.start_agent(
    workflow_id=workflow_id,
    agent="codex",
)

task_id = "{task_id}"

result = {{
    "schema_version": "1.0",
    "task_id": task_id,
    "agent": "codex",
    "status": "SUCCESS",
    "summary": "Crash recovery integration test.",
    "findings": ["Finding 1"],
    "risks": [],
    "recommendations": ["Recommendation 1"],
    "files_changed": [],
    "next_steps": ["Continue workflow"],
}}

result_file = (
    state_manager.PROJECT_ROOT
    / "results"
    / f"{{task_id}}_codex.json"
)

if {register}:
    task_manager.start_agent(
        workflow_id=workflow_id,
        agent="codex",
        task_id=task_id,
        result_file=result_file,
    )

result_file.parent.mkdir(parents=True, exist_ok=True)

result_file.write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

if {complete}:
    task_manager.complete_agent(
        workflow_id=workflow_id,
        agent="codex",
        task_id=task_id,
        result_file=result_file,
    )

# Simulate abrupt process termination.
os._exit(73)
'''

        env = os.environ.copy()
        env["PYTHONPATH"] = (
            str(ORCHESTRATOR_DIR)
            + os.pathsep
            + env.get("PYTHONPATH", "")
        )

        process = subprocess.run(
            [sys.executable, "-c", child_code],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(
            process.returncode,
            73,
            msg=(
                "Child process did not crash as expected:\n"
                f"{process.stdout}\n{process.stderr}"
            ),
        )

        workflow_id = self.marker.read_text(encoding="utf-8")
        self.created_workflows.append(workflow_id)

        result_file = (
            PROJECT_ROOT
            / "results"
            / f"{task_id}_codex.json"
        )
        self.created_results.append(result_file)

        return workflow_id

    def test_crash_after_codex_success_reuses_codex(self):
        workflow_id = self.run_crashed_process(
            "TASK-900001",
            complete_codex=True,
        )

        workflow = state_manager.load_workflow(workflow_id)

        self.assertEqual(workflow["status"], "RUNNING")
        self.assertEqual(
            workflow["agents"]["codex"]["status"],
            "SUCCESS",
        )

        plan = recovery_manager.build_recovery_plan(workflow_id)

        self.assertEqual(
            plan["workflow_status"],
            "INTERRUPTED",
        )
        self.assertEqual(
            plan["completed_agents"],
            ["codex"],
        )
        self.assertEqual(
            plan["pending_agents"],
            ["antigravity"],
        )

        print("\nTC01 PASS: Codex result reused after process crash.")

    def test_crash_after_result_file_before_workflow_update(self):
        workflow_id = self.run_crashed_process(
            "TASK-900002",
            complete_codex=False,
        )

        workflow = state_manager.load_workflow(workflow_id)

        self.assertEqual(
            workflow["agents"]["codex"]["status"],
            "RUNNING",
        )

        orphan_file = self.created_results[-1]
        self.assertTrue(orphan_file.is_file())

        plan = recovery_manager.build_recovery_plan(workflow_id)

        # No registered metadata: orphan result cannot be reused.
        self.assertEqual(plan["completed_agents"], [])
        self.assertEqual(
            plan["pending_agents"],
            ["codex", "antigravity"],
        )

        print(
            "\nTC02 PASS: Unregistered orphan result is not reused."
        )

    def test_crash_after_result_save_recovers_orphan(self):
        workflow_id = self.run_crashed_process(
            "TASK-900003",
            complete_codex=False,
            register_attempt=True,
        )

        workflow = state_manager.load_workflow(workflow_id)

        # The process crashed, so the agent is still RUNNING.
        self.assertEqual(
            workflow["agents"]["codex"]["status"],
            "RUNNING",
        )

        # Metadata must already have been persisted.
        self.assertEqual(
            workflow["agents"]["codex"]["task_id"],
            "TASK-900003",
        )

        result_path = workflow["agents"]["codex"]["result_file"]

        orphan_file = PROJECT_ROOT / result_path

        self.assertTrue(orphan_file.is_file())

        # Recovery should validate and reconcile the orphan result.
        plan = recovery_manager.build_recovery_plan(workflow_id)

        self.assertEqual(
            plan["completed_agents"],
            ["codex"],
        )
        self.assertEqual(
            plan["pending_agents"],
            ["antigravity"],
        )

        # Verify that recovery updated the agent status.
        recovered_workflow = state_manager.load_workflow(workflow_id)

        self.assertEqual(
            recovered_workflow["agents"]["codex"]["status"],
            "SUCCESS",
        )

        print(
            "\nTC03 PASS: Orphan result recovered without rerunning Codex."
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
