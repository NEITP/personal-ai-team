from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'orchestrator'))

import orchestrator.main


def make_workflow(final_report=None):
    return {
        "workflow_id": "WF-202611120001",
        "task": "Test recovery workflow.",
        "agents": {
            "codex": {"status": "SUCCESS"},
            "antigravity": {"status": "SUCCESS"},
        },
        "final_report": final_report,
    }


def make_result(agent, task_id):
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "agent": agent,
        "status": "SUCCESS",
        "summary": f"{agent} test result",
        "findings": [],
        "risks": [],
        "recommendations": [],
        "files_changed": [],
        "next_steps": [],
    }


def make_plan(completed_results=None, pending_agents=None):
    return {
        "recoverable": True,
        "workflow_id": "WF-202611120001",
        "workflow_status": "INTERRUPTED",
        "task": "Test recovery workflow.",
        "completed_agents": [],
        "completed_results": completed_results or [],
        "pending_agents": pending_agents or [],
        "next_agent": None,
        "needs_synthesis": False,
        "final_report_exists": False,
        "warnings": [],
    }


class TestRecoveryScenarios(unittest.TestCase):

    def setUp(self):
        self.workflow_id = "WF-202611120001"

    def setup_mocks(self, workflow, latest_workflow, plan):
        stack = ExitStack()
        mocks = {}

        def add(name, target, **kwargs):
            mocks[name] = stack.enter_context(
                patch(target, **kwargs)
            )
            return mocks[name]

        add(
            "load_workflow",
            "orchestrator.main.recovery_manager.state_manager.load_workflow",
            side_effect=[workflow, latest_workflow],
        )

        add(
            "build_plan",
            "orchestrator.main.recovery_manager.build_recovery_plan",
            return_value=plan,
        )

        add(
            "print_plan",
            "orchestrator.main.recovery_manager.print_recovery_plan",
        )

        add("start_task", "orchestrator.main.task_manager.start_task")
        add("start_agent", "orchestrator.main.task_manager.start_agent")
        add("complete_agent", "orchestrator.main.task_manager.complete_agent")
        add("fail_agent", "orchestrator.main.task_manager.fail_agent")

        add(
            "finish_task",
            "orchestrator.main.task_manager.finish_task",
            return_value={"status": "SUCCESS"},
        )

        add(
            "update_status",
            "orchestrator.main.task_manager.state_manager.update_workflow_status",
            return_value={"status": "PARTIAL"},
        )

        add(
            "clear_report",
            "orchestrator.main.recovery_manager.state_manager.clear_final_report",
        )

        add(
            "check_report",
            "orchestrator.main.recovery_manager.check_final_report",
            return_value=False,
        )

        add("run_agent", "orchestrator.main.run_agent")

        add(
            "synthesizer",
            "orchestrator.main.run_final_synthesizer",
            return_value=Path("results/new-report.md"),
        )

        return stack, mocks

    def execute(self, workflow, latest, plan, run_results=None):
        stack, mocks = self.setup_mocks(
            workflow,
            latest,
            plan,
        )

        if run_results is not None:
            mocks["run_agent"].side_effect = run_results

        output = StringIO()

        try:
            with redirect_stdout(output):
                from orchestrator.main import resume_workflow
                resume_workflow(self.workflow_id)
        finally:
            stack.close()

        return mocks, output.getvalue()

    # TC01: Retrying Codex must also retry Antigravity.
    def test_retry_codex_also_retries_antigravity(self):
        old_antigravity = make_result(
            "antigravity",
            "TASK-OLD-002",
        )

        new_codex = make_result(
            "codex",
            "TASK-NEW-001",
        )

        new_antigravity = make_result(
            "antigravity",
            "TASK-NEW-002",
        )

        workflow = make_workflow("results/old-report.md")
        latest = make_workflow(None)

        plan = make_plan(
            completed_results=[old_antigravity],
            pending_agents=["codex"],
        )

        mocks, _ = self.execute(
            workflow,
            latest,
            plan,
            [new_codex, new_antigravity],
        )

        self.assertEqual(
            mocks["run_agent"].call_count,
            2,
        )

        calls = mocks["run_agent"].call_args_list

        self.assertEqual(calls[0].args[0], "codex")
        self.assertEqual(calls[1].args[0], "antigravity")

        # Antigravity must receive the new Codex result.
        self.assertEqual(
            calls[1].args[2]["task_id"],
            "TASK-NEW-001",
        )

        mocks["clear_report"].assert_called_once_with(
            self.workflow_id
        )

        mocks["synthesizer"].assert_called_once()

        mocks["finish_task"].assert_called_once_with(
            workflow_id=self.workflow_id,
            final_report=Path("results/new-report.md"),
        )

    # TC02: Reuse the report when no agent needs to rerun.
    def test_reuse_report_when_all_agents_are_reusable(self):
        codex = make_result("codex", "TASK-OLD-001")
        antigravity = make_result("antigravity", "TASK-OLD-002")

        workflow = make_workflow("results/old-report.md")
        latest = make_workflow("results/old-report.md")

        plan = make_plan(
            completed_results=[codex, antigravity],
            pending_agents=[],
        )

        stack, mocks = self.setup_mocks(
            workflow,
            latest,
            plan,
        )

        mocks["check_report"].return_value = True

        try:
            with redirect_stdout(StringIO()):
                from orchestrator.main import resume_workflow
                resume_workflow(self.workflow_id)
        finally:
            stack.close()

        mocks["run_agent"].assert_not_called()
        mocks["clear_report"].assert_not_called()
        mocks["synthesizer"].assert_not_called()

        mocks["finish_task"].assert_called_once_with(
            workflow_id=self.workflow_id,
            final_report="results/old-report.md",
        )

    # TC03: Stop after the configured retry limit is exhausted.
    def test_agent_failure_stops_workflow_and_skips_synthesis(self):
        workflow = make_workflow("results/old-report.md")
        latest = make_workflow(None)

        plan = make_plan(
            completed_results=[],
            pending_agents=["codex", "antigravity"],
        )

        mocks, _ = self.execute(
            workflow,
            latest,
            plan,
            [False, False],
        )

        mocks["fail_agent"].assert_called_once()

        self.assertEqual(mocks["run_agent"].call_count, 2)

        mocks["synthesizer"].assert_not_called()

        mocks["finish_task"].assert_called_once_with(
            workflow_id=self.workflow_id,
            final_report=None,
        )

    # TC04: Synthesis failure must result in PARTIAL.
    def test_synthesis_failure_marks_workflow_partial(self):
        codex = make_result("codex", "TASK-NEW-001")
        antigravity = make_result("antigravity", "TASK-NEW-002")

        workflow = make_workflow(None)
        latest = make_workflow(None)

        plan = make_plan(
            completed_results=[],
            pending_agents=["codex", "antigravity"],
        )

        stack, mocks = self.setup_mocks(
            workflow,
            latest,
            plan,
        )

        mocks["run_agent"].side_effect = [
            codex,
            antigravity,
        ]

        mocks["synthesizer"].return_value = False

        try:
            with redirect_stdout(StringIO()):
                from orchestrator.main import resume_workflow
                resume_workflow(self.workflow_id)
        finally:
            stack.close()

        self.assertEqual(
            mocks["run_agent"].call_count,
            2,
        )

        mocks["synthesizer"].assert_called_once()

        mocks["update_status"].assert_called_once_with(
            self.workflow_id,
            "PARTIAL",
            error="Agents completed, but synthesis failed.",
        )

    def test_parallel_recovery_reuses_finished_agent_and_retries_only_pending(self):
        codex = make_result("codex", "TASK-OLD-001")
        new_antigravity = make_result("antigravity", "TASK-NEW-002")

        workflow = make_workflow(None)
        workflow["execution_mode"] = "parallel"
        latest = make_workflow(None)
        latest["execution_mode"] = "parallel"
        plan = make_plan(
            completed_results=[codex],
            pending_agents=["antigravity"],
        )

        stack, mocks = self.setup_mocks(workflow, latest, plan)
        parallel_call = stack.enter_context(
            patch(
                "orchestrator.main.run_parallel_agents",
                return_value=[new_antigravity],
            )
        )

        try:
            with redirect_stdout(StringIO()):
                from orchestrator.main import resume_workflow
                result = resume_workflow(self.workflow_id)
        finally:
            stack.close()

        self.assertEqual(result, 0)
        parallel_call.assert_called_once_with(
            "Test recovery workflow.",
            ["antigravity"],
            self.workflow_id,
        )
        mocks["run_agent"].assert_not_called()
        mocks["synthesizer"].assert_called_once()
        synthesized_results = mocks["synthesizer"].call_args.args[1]
        self.assertEqual(
            [item["task_id"] for item in synthesized_results],
            ["TASK-OLD-001", "TASK-NEW-002"],
        )

    def test_parallel_recovery_failure_keeps_success_and_skips_synthesis(self):
        codex = make_result("codex", "TASK-OLD-001")
        workflow = make_workflow(None)
        workflow["execution_mode"] = "parallel"
        latest = make_workflow(None)
        latest["execution_mode"] = "parallel"
        plan = make_plan(
            completed_results=[codex],
            pending_agents=["antigravity"],
        )

        stack, mocks = self.setup_mocks(workflow, latest, plan)
        parallel_call = stack.enter_context(
            patch(
                "orchestrator.main.run_parallel_agents",
                return_value=[False],
            )
        )
        try:
            with redirect_stdout(StringIO()):
                from orchestrator.main import resume_workflow
                result = resume_workflow(self.workflow_id)
        finally:
            stack.close()

        self.assertEqual(result, 0)
        parallel_call.assert_called_once_with(
            "Test recovery workflow.",
            ["antigravity"],
            self.workflow_id,
        )
        mocks["synthesizer"].assert_not_called()
        mocks["finish_task"].assert_called_once_with(
            workflow_id=self.workflow_id,
            final_report=None,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
