
import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from orchestrator import recovery_manager


class TestRecoveryManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)

        self.project_patch = patch(
            "orchestrator.recovery_manager.PROJECT_ROOT",
            self.project_root,
        )
        self.project_patch.start()

        self.results_dir = self.project_root / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.valid_result = {
            "schema_version": "1.0",
            "task_id": "TASK-001",
            "agent": "codex",
            "status": "SUCCESS",
            "summary": "Synthetic test result.",
            "findings": ["Test finding."],
            "risks": [],
            "recommendations": [],
            "files_changed": [],
            "next_steps": [],
        }

    def tearDown(self):
        self.project_patch.stop()
        self.temp_dir.cleanup()

    def write_result(self, filename, result):
        path = self.results_dir / filename

        with path.open("w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)

        return path

    def test_resolve_project_file_valid(self):
        path = recovery_manager.resolve_project_file(
            "results/test.json"
        )

        self.assertEqual(
            path,
            self.results_dir / "test.json",
        )

    def test_resolve_project_file_outside_project(self):
        path = recovery_manager.resolve_project_file(
            "../outside.json"
        )

        self.assertIsNone(path)

    def test_load_valid_agent_result_success(self):
        self.write_result("codex.json", self.valid_result)

        agent_state = {
            "task_id": "TASK-001",
            "result_file": "results/codex.json",
        }

        result, error = recovery_manager.load_valid_agent_result(
            agent_state,
            "codex",
        )

        self.assertIsNone(error)
        self.assertEqual(result["task_id"], "TASK-001")
        self.assertEqual(result["agent"], "codex")

    def test_load_result_missing_result_file(self):
        result, error = recovery_manager.load_valid_agent_result(
            {"task_id": "TASK-001"},
            "codex",
        )

        self.assertIsNone(result)
        self.assertEqual(
            error,
            "Missing result_file or task_id.",
        )

    def test_load_result_missing_task_id(self):
        result, error = recovery_manager.load_valid_agent_result(
            {"result_file": "results/codex.json"},
            "codex",
        )

        self.assertIsNone(result)
        self.assertEqual(
            error,
            "Missing result_file or task_id.",
        )

    def test_load_result_file_not_found(self):
        agent_state = {
            "task_id": "TASK-001",
            "result_file": "results/missing.json",
        }

        result, error = recovery_manager.load_valid_agent_result(
            agent_state,
            "codex",
        )

        self.assertIsNone(result)
        self.assertEqual(
            error,
            "Result file does not exist.",
        )

    def test_load_result_invalid_json(self):
        path = self.results_dir / "invalid.json"
        path.write_text("{ invalid json", encoding="utf-8")

        agent_state = {
            "task_id": "TASK-001",
            "result_file": "results/invalid.json",
        }

        result, error = recovery_manager.load_valid_agent_result(
            agent_state,
            "codex",
        )

        self.assertIsNone(result)
        self.assertIn("Cannot read result JSON:", error)

    def test_load_result_json_not_object(self):
        path = self.results_dir / "array.json"
        path.write_text("[]", encoding="utf-8")

        agent_state = {
            "task_id": "TASK-001",
            "result_file": "results/array.json",
        }

        result, error = recovery_manager.load_valid_agent_result(
            agent_state,
            "codex",
        )

        self.assertIsNone(result)
        self.assertEqual(
            error,
            "Result must be a JSON object.",
        )

    def test_load_result_invalid_schema(self):
        invalid_result = {
            "task_id": "TASK-001",
            "agent": "codex",
        }

        self.write_result("invalid_schema.json", invalid_result)

        agent_state = {
            "task_id": "TASK-001",
            "result_file": "results/invalid_schema.json",
        }

        result, error = recovery_manager.load_valid_agent_result(
            agent_state,
            "codex",
        )

        self.assertIsNone(result)
        self.assertIn("Result schema invalid:", error)

    def test_load_result_task_id_mismatch(self):
        wrong_result = self.valid_result.copy()
        wrong_result["task_id"] = "TASK-999"

        self.write_result("wrong_task.json", wrong_result)

        agent_state = {
            "task_id": "TASK-001",
            "result_file": "results/wrong_task.json",
        }

        result, error = recovery_manager.load_valid_agent_result(
            agent_state,
            "codex",
        )

        self.assertIsNone(result)
        self.assertEqual(
            error,
            "Result task_id does not match workflow state.",
        )

    def test_load_result_agent_mismatch(self):
        wrong_result = self.valid_result.copy()
        wrong_result["agent"] = "antigravity"

        self.write_result("wrong_agent.json", wrong_result)

        agent_state = {
            "task_id": "TASK-001",
            "result_file": "results/wrong_agent.json",
        }

        result, error = recovery_manager.load_valid_agent_result(
            agent_state,
            "codex",
        )

        self.assertIsNone(result)
        self.assertEqual(
            error,
            "Result agent does not match workflow state.",
        )

    def test_load_result_partial_status_not_reusable(self):
        partial_result = self.valid_result.copy()
        partial_result["status"] = "PARTIAL"

        self.write_result("partial.json", partial_result)

        agent_state = {
            "task_id": "TASK-001",
            "result_file": "results/partial.json",
        }

        result, error = recovery_manager.load_valid_agent_result(
            agent_state,
            "codex",
        )

        self.assertIsNone(result)
        self.assertEqual(
            error,
            "Only SUCCESS results can be reused.",
        )

    def test_check_final_report_exists(self):
        report_path = self.project_root / "results" / "final.md"
        report_path.write_text("# Test report", encoding="utf-8")

        workflow = {
            "final_report": "results/final.md",
        }

        self.assertTrue(
            recovery_manager.check_final_report(workflow)
        )

    def test_check_final_report_missing(self):
        workflow = {
            "final_report": "results/missing.md",
        }

        self.assertFalse(
            recovery_manager.check_final_report(workflow)
        )

    def test_build_recovery_plan_running_workflow(self):
        self.write_result("codex.json", self.valid_result)

        workflow = {
            "workflow_id": "WF-TEST-001",
            "status": "RUNNING",
            "task": "Test recovery plan.",
            "final_report": None,
            "agents": {
                "codex": {
                    "status": "SUCCESS",
                    "task_id": "TASK-001",
                    "result_file": "results/codex.json",
                },
                "antigravity": {
                    "status": "PENDING",
                    "task_id": None,
                    "result_file": None,
                },
            },
        }

        interrupted_workflow = {
            **workflow,
            "status": "INTERRUPTED",
        }

        with patch(
            "orchestrator.recovery_manager.state_manager.load_workflow",
            side_effect=[workflow, interrupted_workflow],
        ) as mock_load, patch(
            "orchestrator.recovery_manager.state_manager.update_workflow_status"
        ) as mock_update:

            plan = recovery_manager.build_recovery_plan(
                "WF-TEST-001"
            )

        mock_update.assert_called_once_with(
            "WF-TEST-001",
            "INTERRUPTED",
            error="Running workflow detected during recovery scan.",
        )

        self.assertEqual(mock_load.call_count, 1)
        self.assertEqual(plan["workflow_status"], "INTERRUPTED")
        self.assertEqual(plan["completed_agents"], ["codex"])
        self.assertEqual(plan["pending_agents"], ["antigravity"])
        self.assertEqual(plan["next_agent"], "antigravity")
        self.assertEqual(len(plan["completed_results"]), 1)
        self.assertFalse(plan["needs_synthesis"])

    def test_build_recovery_plan_already_successful(self):
        workflow = {
            "workflow_id": "WF-TEST-002",
            "status": "SUCCESS",
            "final_report": None,
            "agents": {},
        }

        with patch(
            "orchestrator.recovery_manager.state_manager.load_workflow",
            return_value=workflow,
        ):

            plan = recovery_manager.build_recovery_plan(
                "WF-TEST-002"
            )

        self.assertFalse(plan["recoverable"])
        self.assertEqual(
            plan["reason"],
            "Workflow already completed successfully.",
        )
        self.assertFalse(plan["needs_synthesis"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
