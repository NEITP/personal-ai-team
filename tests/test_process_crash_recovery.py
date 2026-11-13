
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_DIR = PROJECT_ROOT / "orchestrator"

sys.path.insert(0, str(ORCHESTRATOR_DIR))

import state_manager
import recovery_manager
from orchestrator import main as orchestrator_main


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

    def run_crashed_parallel_process(self):
        marker = repr(str(self.marker))
        child_code = f'''
import json
import os
import threading
from pathlib import Path

import state_manager
import task_manager

workflow = task_manager.create_task(
    task="Real parallel process crash recovery test.",
    agents=["codex", "antigravity"],
    execution_mode="parallel",
)
workflow_id = workflow["workflow_id"]
Path({marker}).write_text(workflow_id, encoding="utf-8")
task_manager.start_task(workflow_id)

suffix = workflow_id.removeprefix("WF-")
codex_task_id = "TASK-" + suffix + "01"
antigravity_task_id = "TASK-" + suffix + "02"
codex_file = state_manager.PROJECT_ROOT / "results" / f"{{codex_task_id}}_codex.json"
antigravity_file = state_manager.PROJECT_ROOT / "results" / f"{{antigravity_task_id}}_antigravity.json"
antigravity_running = threading.Event()
codex_completed = threading.Event()

def complete_codex():
    task_manager.start_agent(
        workflow_id, "codex", task_id=codex_task_id, result_file=codex_file
    )
    result = {{
        "schema_version": "1.0",
        "task_id": codex_task_id,
        "agent": "codex",
        "status": "SUCCESS",
        "summary": "Parallel child completed Codex before crash.",
        "findings": ["Codex completed."],
        "risks": [],
        "recommendations": [],
        "files_changed": [],
        "next_steps": [],
    }}
    codex_file.parent.mkdir(parents=True, exist_ok=True)
    codex_file.write_text(json.dumps(result), encoding="utf-8")
    task_manager.complete_agent(
        workflow_id, "codex", task_id=codex_task_id, result_file=codex_file
    )
    codex_completed.set()

def leave_antigravity_running():
    task_manager.start_agent(
        workflow_id,
        "antigravity",
        task_id=antigravity_task_id,
        result_file=antigravity_file,
    )
    antigravity_running.set()
    threading.Event().wait()

threading.Thread(target=complete_codex, daemon=True).start()
threading.Thread(target=leave_antigravity_running, daemon=True).start()
if not codex_completed.wait(10) or not antigravity_running.wait(10):
    os._exit(74)

# Abruptly terminate while another independent agent remains RUNNING.
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
                "Parallel child did not terminate at the crash point:\n"
                f"{process.stdout}\n{process.stderr}"
            ),
        )

        workflow_id = self.marker.read_text(encoding="utf-8")
        self.created_workflows.append(workflow_id)
        suffix = workflow_id.removeprefix("WF-")
        for agent, ending in (("codex", "01"), ("antigravity", "02")):
            self.created_results.append(
                PROJECT_ROOT
                / "results"
                / f"TASK-{suffix}{ending}_{agent}.json"
            )
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

    def test_parallel_process_crash_reuses_completed_agent_and_retries_running_agent(self):
        workflow_id = self.run_crashed_parallel_process()
        workflow = state_manager.load_workflow(workflow_id)

        self.assertEqual(workflow["execution_mode"], "parallel")
        self.assertEqual(workflow["status"], "RUNNING")
        self.assertEqual(workflow["agents"]["codex"]["status"], "SUCCESS")
        self.assertEqual(
            workflow["agents"]["antigravity"]["status"],
            "RUNNING",
        )

        plan = recovery_manager.build_recovery_plan(workflow_id)

        self.assertEqual(plan["workflow_status"], "INTERRUPTED")
        self.assertEqual(plan["completed_agents"], ["codex"])
        self.assertEqual(plan["pending_agents"], ["antigravity"])
        self.assertEqual(workflow["execution_mode"], "parallel")

        def fake_agent_run(agent, prompt, agent_config, project_root, timeout_seconds):
            task_match = re.search(r'"task_id":\s*"(TASK-[0-9]+)"', prompt)
            self.assertIsNotNone(task_match)
            result = {
                "schema_version": "1.0",
                "task_id": task_match.group(1),
                "agent": agent,
                "status": "SUCCESS",
                "summary": f"Recovered {agent} result.",
                "findings": ["Agent completed after recovery."],
                "risks": [],
                "recommendations": [],
                "files_changed": [],
                "next_steps": [],
            }
            return subprocess.CompletedProcess(
                [agent],
                0,
                json.dumps(result),
                "",
            )

        report_file = (
            PROJECT_ROOT / "results" / f"FINAL-WORKFLOW-{workflow_id}.md"
        )
        self.created_results.append(report_file)
        runtime_configuration = dict(orchestrator_main.CONFIGURATION)
        runtime_configuration["agents"] = {"antigravity": {"command": "agy"}}
        try:
            with patch.object(orchestrator_main, "CONFIGURATION", runtime_configuration), patch.object(
                orchestrator_main.agent_adapters, "is_available", return_value=True
            ), patch.object(
                orchestrator_main.agent_adapters,
                "run",
                side_effect=fake_agent_run,
            ) as run_agent, patch.object(
                orchestrator_main.agent_adapters,
                "run_codex",
                return_value=subprocess.CompletedProcess(
                    ["codex"],
                    0,
                    "# Recovered parallel workflow\n",
                    "",
                ),
            ):
                result = orchestrator_main.resume_workflow(workflow_id)

            self.assertEqual(result, 0)
            self.assertEqual(run_agent.call_count, 1)
            self.assertEqual(run_agent.call_args.kwargs["agent"], "antigravity")
            self.assertTrue(report_file.is_file())
            completed = state_manager.load_workflow(workflow_id)
            self.assertEqual(completed["status"], "SUCCESS")
            self.assertEqual(completed["execution_mode"], "parallel")
            self.assertTrue(all(
                item["status"] == "SUCCESS"
                for item in completed["agents"].values()
            ))
            recovered_result = Path(
                completed["agents"]["antigravity"]["result_file"]
            )
            if not recovered_result.is_absolute():
                recovered_result = PROJECT_ROOT / recovered_result
            self.created_results.append(recovered_result)
        finally:
            if report_file in self.created_results and not report_file.exists():
                self.created_results.remove(report_file)

        print(
            "\nTC04 PASS: Parallel process crash is recovered through "
            "workflow completion without rerunning the completed agent."
        )

    def test_workflow_lease_prevents_second_process_from_resuming_same_workflow(self):
        workflows_dir = Path(self.temp_dir.name) / "workflows"
        child_marker = Path(self.temp_dir.name) / "lease-held.txt"
        workflow_id = "WF-20261113000123456789"
        code = f'''
import time
from pathlib import Path
import state_manager

state_manager.WORKFLOW_DIR = Path({str(workflows_dir)!r})
with state_manager.workflow_lease({workflow_id!r}, timeout=5):
    Path({str(child_marker)!r}).write_text("held", encoding="utf-8")
    time.sleep(4)
'''
        environment = os.environ.copy()
        environment["PYTHONPATH"] = (
            str(ORCHESTRATOR_DIR)
            + os.pathsep
            + environment.get("PYTHONPATH", "")
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        previous_workflows_dir = state_manager.WORKFLOW_DIR
        state_manager.WORKFLOW_DIR = workflows_dir
        try:
            deadline = time.monotonic() + 10
            while not child_marker.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(child_marker.exists(), "child process did not acquire lease")
            with self.assertRaises(state_manager.WorkflowBusyError):
                with state_manager.workflow_lease(workflow_id, timeout=0.15):
                    pass
        finally:
            process.terminate()
            process.communicate(timeout=10)
            state_manager.WORKFLOW_DIR = previous_workflows_dir


if __name__ == "__main__":
    unittest.main(verbosity=2)
