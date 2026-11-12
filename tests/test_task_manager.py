
import unittest
from unittest.mock import patch

from orchestrator import task_manager


class TestTaskManager(unittest.TestCase):

    @patch("orchestrator.task_manager.state_manager.create_workflow")
    def test_create_task(self, mock_create):
        expected = {
            "workflow_id": "WF-TEST-001",
            "status": "PENDING",
        }
        mock_create.return_value = expected

        result = task_manager.create_task(
            "Test task",
            ["codex", "antigravity"],
        )

        mock_create.assert_called_once_with(
            original_task="Test task",
            agents=["codex", "antigravity"],
        )
        self.assertEqual(result, expected)

    @patch("orchestrator.task_manager.state_manager.update_workflow_status")
    def test_start_task(self, mock_update):
        mock_update.return_value = {
            "workflow_id": "WF-TEST-001",
            "status": "RUNNING",
        }

        result = task_manager.start_task("WF-TEST-001")

        mock_update.assert_called_once_with(
            "WF-TEST-001",
            "RUNNING",
        )
        self.assertEqual(result["status"], "RUNNING")

    @patch("orchestrator.task_manager.state_manager.update_agent_status")
    def test_start_agent(self, mock_update):
        task_manager.start_agent(
            "WF-TEST-001",
            "codex",
            task_id="TASK-001",
        )

        mock_update.assert_called_once_with(
            workflow_id="WF-TEST-001",
            agent="codex",
            status="RUNNING",
            task_id="TASK-001",
        )

    @patch("orchestrator.task_manager.state_manager.update_agent_status")
    def test_complete_agent_success(self, mock_update):
        task_manager.complete_agent(
            "WF-TEST-001",
            "codex",
            task_id="TASK-001",
            result_file="results/TASK-001.json",
        )

        mock_update.assert_called_once_with(
            workflow_id="WF-TEST-001",
            agent="codex",
            status="SUCCESS",
            task_id="TASK-001",
            result_file="results/TASK-001.json",
        )

    @patch("orchestrator.task_manager.state_manager.update_agent_status")
    def test_complete_agent_partial(self, mock_update):
        task_manager.complete_agent(
            "WF-TEST-001",
            "codex",
            partial=True,
        )

        self.assertEqual(
            mock_update.call_args.kwargs["status"],
            "PARTIAL",
        )

    @patch("orchestrator.task_manager.state_manager.update_agent_status")
    def test_fail_agent(self, mock_update):
        task_manager.fail_agent(
            "WF-TEST-001",
            "codex",
            "Simulated failure",
            task_id="TASK-001",
        )

        mock_update.assert_called_once_with(
            workflow_id="WF-TEST-001",
            agent="codex",
            status="FAILED",
            task_id="TASK-001",
            error="Simulated failure",
        )

    @patch("orchestrator.task_manager.state_manager.update_agent_status")
    def test_skip_agent(self, mock_update):
        task_manager.skip_agent(
            "WF-TEST-001",
            "antigravity",
            reason="Previous agent failed",
        )

        self.assertEqual(
            mock_update.call_args.kwargs["status"],
            "SKIPPED",
        )

    @patch("orchestrator.task_manager.state_manager.update_workflow_status")
    @patch("orchestrator.task_manager.state_manager.load_workflow")
    def test_finish_task_success(self, mock_load, mock_update):
        mock_load.return_value = {
            "agents": {
                "codex": {"status": "SUCCESS"},
                "antigravity": {"status": "SUCCESS"},
            }
        }

        task_manager.finish_task("WF-TEST-001")

        mock_update.assert_called_once_with(
            "WF-TEST-001",
            "SUCCESS",
        )

    @patch("orchestrator.task_manager.state_manager.update_workflow_status")
    @patch("orchestrator.task_manager.state_manager.load_workflow")
    def test_finish_task_partial(self, mock_load, mock_update):
        mock_load.return_value = {
            "agents": {
                "codex": {"status": "SUCCESS"},
                "antigravity": {"status": "FAILED"},
            }
        }

        task_manager.finish_task("WF-TEST-001")

        mock_update.assert_called_once_with(
            "WF-TEST-001",
            "PARTIAL",
        )

    @patch("orchestrator.task_manager.state_manager.update_workflow_status")
    @patch("orchestrator.task_manager.state_manager.load_workflow")
    def test_finish_task_failed(self, mock_load, mock_update):
        mock_load.return_value = {
            "agents": {
                "codex": {"status": "FAILED"},
                "antigravity": {"status": "SKIPPED"},
            }
        }

        task_manager.finish_task("WF-TEST-001")

        mock_update.assert_called_once_with(
            "WF-TEST-001",
            "FAILED",
        )

    @patch("orchestrator.task_manager.state_manager.set_final_report")
    @patch("orchestrator.task_manager.state_manager.update_workflow_status")
    @patch("orchestrator.task_manager.state_manager.load_workflow")
    def test_finish_task_saves_report(
        self,
        mock_load,
        mock_update,
        mock_report,
    ):
        mock_load.return_value = {
            "agents": {
                "codex": {"status": "SUCCESS"},
            }
        }

        task_manager.finish_task(
            "WF-TEST-001",
            final_report="results/final.md",
        )

        mock_report.assert_called_once_with(
            "WF-TEST-001",
            "results/final.md",
        )

        mock_update.assert_called_once_with(
            "WF-TEST-001",
            "SUCCESS",
        )

    @patch("orchestrator.task_manager.state_manager.update_workflow_status")
    @patch("orchestrator.task_manager.state_manager.get_incomplete_workflows")
    def test_recover_tasks_only_running(
        self,
        mock_incomplete,
        mock_update,
    ):
        mock_incomplete.return_value = [
            {
                "workflow_id": "WF-RUNNING",
                "status": "RUNNING",
            },
            {
                "workflow_id": "WF-INTERRUPTED",
                "status": "INTERRUPTED",
            },
            {
                "workflow_id": "WF-PENDING",
                "status": "PENDING",
            },
        ]

        result = task_manager.recover_tasks()

        self.assertEqual(result, ["WF-RUNNING"])

        mock_update.assert_called_once_with(
            "WF-RUNNING",
            "INTERRUPTED",
            error="Workflow was interrupted before completion.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
