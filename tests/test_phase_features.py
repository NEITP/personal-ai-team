from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import subprocess
import unittest
from unittest.mock import patch

from orchestrator import agent_adapters, cli, main, retention, state_manager
from orchestrator.configuration import agents_for_route, load_configuration


class TestPhaseFeatures(unittest.TestCase):

    def test_default_template_has_no_preselected_agents_or_routes(self):
        configuration = load_configuration()
        self.assertEqual(configuration["agents"], {})
        self.assertEqual(configuration["routes"], {})

    def test_run_without_configured_agents_explains_setup(self):
        output = StringIO()
        with redirect_stdout(output):
            result = main.main(["run", "hello"])
        self.assertEqual(result, 2)
        self.assertIn("Add one in config/agents.yaml", output.getvalue())

    def test_generic_command_adapter_accepts_custom_agent_id(self):
        command, stdin = agent_adapters.build_command(
            "my_assistant",
            "do a task",
            {
                "command": "my-ai-cli",
                "adapter": "command",
                "args": ["--prompt", "{prompt}", "--cwd", "{project_root}"],
                "prompt_mode": "argument",
            },
            Path("/workspace"),
        )
        self.assertEqual(
            command,
            ["my-ai-cli", "--prompt", "do a task", "--cwd", str(Path("/workspace"))],
        )
        self.assertIsNone(stdin)

    def test_technical_research_route_includes_sequential_reviewer(self):
        configuration = load_configuration()
        configuration["agents"] = {"finder": {}, "checker": {}}
        configuration["max_agents"] = 2
        configuration["routes"] = {
            "research": {
                "primary": "finder", "reviewer": "checker",
                "require_review": True, "execution": "sequential",
            }
        }
        self.assertEqual(
            agents_for_route(configuration, "research"),
            ["finder", "checker"],
        )

    def test_agent_call_retries_only_up_to_configured_limit(self):
        configuration = dict(main.CONFIGURATION)
        configuration["max_retries"] = 2
        successful_result = {"agent": "codex", "status": "SUCCESS"}
        with patch.object(main, "CONFIGURATION", configuration), patch.object(
            main,
            "run_agent",
            side_effect=[False, False, successful_result],
        ) as run_agent:
            with redirect_stdout(StringIO()):
                result = main.run_agent_with_retries("codex", "task")

        self.assertEqual(result, successful_result)
        self.assertEqual(run_agent.call_count, 3)

    def test_logging_policy_omits_sensitive_payloads(self):
        configuration = dict(main.CONFIGURATION)
        configuration["preserve_logs"] = True
        configuration["logging"] = {
            "include_prompt": False,
            "include_raw_output": False,
            "include_diagnostics": False,
            "include_structured_result": False,
        }
        with TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "agent_runs.log"
            with patch.object(main, "CONFIGURATION", configuration), patch.object(
                main, "LOG_DIR", Path(temp_dir)
            ), patch.object(main, "LOG_FILE", log_path):
                main.save_log(
                    "codex",
                    "prompt-secret-marker",
                    "output-secret-marker",
                    "diagnostic-secret-marker",
                    0,
                    "SUCCESS",
                    0.2,
                    {"summary": "result-secret-marker"},
                )

            log_text = log_path.read_text(encoding="utf-8")
            for marker in (
                "prompt-secret-marker",
                "output-secret-marker",
                "diagnostic-secret-marker",
                "result-secret-marker",
            ):
                self.assertNotIn(marker, log_text)

    def test_context_loader_blocks_secret_filename_patterns(self):
        configuration = dict(main.CONFIGURATION)
        configuration["context"] = {
            **main.CONFIGURATION["context"],
            "show_loaded_files": False,
            "restrict_workspace": True,
        }
        patterns = ("*secret*", ".env", ".env.*")

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "safe.md").write_text("safe context", encoding="utf-8")
            (root / "secret-notes.txt").write_text(
                "private context",
                encoding="utf-8",
            )
            with patch.object(main, "PROJECT_ROOT", root), patch.object(
                main, "CONFIGURATION", configuration
            ), patch.object(main, "BLOCKED_FILE_PATTERNS", patterns):
                enhanced, loaded = main.read_task_files(
                    "Read safe.md and secret-notes.txt"
                )

        self.assertEqual(loaded, ["safe.md"])
        self.assertIn("safe context", enhanced)
        self.assertNotIn("private context", enhanced)

    def test_context_loader_blocks_secrets_in_normal_filename(self):
        configuration = dict(main.CONFIGURATION)
        configuration["context"] = {
            **main.CONFIGURATION["context"], "show_loaded_files": False,
            "restrict_workspace": True, "scan_secret_content": True,
        }
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes.md").write_text(
                "api_key = 'abcdefghijklmnop'", encoding="utf-8"
            )
            with patch.object(main, "PROJECT_ROOT", root), patch.object(
                main, "CONFIGURATION", configuration
            ):
                enhanced, loaded = main.read_task_files("Read notes.md")
        self.assertEqual(loaded, [])
        self.assertNotIn("abcdefghijklmnop", enhanced)

    def test_status_hides_task_unless_explicitly_requested(self):
        workflow = {"workflow_id": "WF-test", "status": "FAILED", "task": "private marker", "agents": {}}
        runtime = type("Runtime", (), {"task_manager": type(
            "Tasks", (), {"get_task": staticmethod(lambda _id: workflow)}
        )})()
        hidden = StringIO()
        with redirect_stdout(hidden):
            self.assertTrue(cli.show_workflow_status(runtime, "WF-test"))
        shown = StringIO()
        with redirect_stdout(shown):
            self.assertTrue(cli.show_workflow_status(runtime, "WF-test", show_task=True))
        self.assertNotIn("private marker", hidden.getvalue())
        self.assertIn("private marker", shown.getvalue())

    def test_version_probe_returns_first_line(self):
        completed = subprocess.CompletedProcess(["codex", "--version"], 0, "codex 1.2.3\nextra\n", "")
        with patch("orchestrator.agent_adapters.subprocess.run", return_value=completed):
            self.assertEqual(
                agent_adapters.probe_version("codex", {"command": "codex"}),
                "codex 1.2.3",
            )

    def test_parallel_agents_finish_and_keep_state_for_both_workers(self):
        barrier = Barrier(2)

        def fake_run(agent, prompt, previous_result=None, workflow_id=None):
            self.assertIsNone(previous_result)
            barrier.wait(timeout=5)
            return {
                "task_id": f"TASK-TEST-{agent}",
                "agent": agent,
                "status": "SUCCESS",
            }

        with TemporaryDirectory() as temp_dir:
            with patch.object(state_manager, "WORKFLOW_DIR", Path(temp_dir)):
                workflow = state_manager.create_workflow(
                    "parallel task",
                    ["codex", "antigravity"],
                )
                state_manager.update_workflow_status(
                    workflow["workflow_id"],
                    "RUNNING",
                )
                with patch.object(main, "run_agent", side_effect=fake_run):
                    results = main.run_parallel_agents(
                        "parallel task",
                        ["codex", "antigravity"],
                        workflow["workflow_id"],
                    )

                saved = state_manager.load_workflow(workflow["workflow_id"])

        self.assertEqual(
            [result["agent"] for result in results],
            ["codex", "antigravity"],
        )
        self.assertTrue(all(
            agent_state["status"] == "SUCCESS"
            for agent_state in saved["agents"].values()
        ))

    def test_parallel_worker_failure_is_recorded_and_returned(self):
        successful = {
            "task_id": "TASK-TEST-codex",
            "agent": "codex",
            "status": "SUCCESS",
        }
        with TemporaryDirectory() as temp_dir:
            with patch.object(state_manager, "WORKFLOW_DIR", Path(temp_dir)):
                workflow = state_manager.create_workflow(
                    "parallel failure task",
                    ["codex", "antigravity"],
                    execution_mode="parallel",
                )
                state_manager.update_workflow_status(
                    workflow["workflow_id"],
                    "RUNNING",
                )
                with patch.object(
                    main,
                    "run_agent_with_retries",
                    side_effect=[successful, False],
                ):
                    results = main.run_parallel_agents(
                        "parallel failure task",
                        ["codex", "antigravity"],
                        workflow["workflow_id"],
                    )
                saved = state_manager.load_workflow(workflow["workflow_id"])

        self.assertEqual(results[0], successful)
        self.assertFalse(results[1])
        self.assertEqual(saved["agents"]["codex"]["status"], "SUCCESS")
        self.assertEqual(saved["agents"]["antigravity"]["status"], "FAILED")

    def test_ollama_adapter_does_not_run_missing_model(self):
        agent_config = {
            "command": "ollama",
            "model": "model-not-installed",
        }
        list_result = subprocess.CompletedProcess(
            ["ollama", "list"],
            0,
            "NAME ID SIZE\n",
            "",
        )
        with patch(
            "orchestrator.agent_adapters.subprocess.run",
            return_value=list_result,
        ) as run:
            with self.assertRaises(agent_adapters.AgentAdapterError):
                agent_adapters.run(
                    "ollama",
                    "prompt",
                    agent_config,
                    Path.cwd(),
                    10,
                )

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["ollama", "list"])

    def test_cli_refuses_parallel_execution_for_review_route(self):
        configuration = dict(main.CONFIGURATION)
        configuration["agents"] = {"builder": {}, "reviewer": {}}
        configuration["routes"] = {
            name: {
                "primary": "builder", "reviewer": "reviewer",
                "require_review": True, "execution": "sequential",
            }
            for name in ("architecture", "research")
        }
        for route in configuration["routes"]:
            with self.subTest(route=route):
                output = StringIO()
                with patch.object(main, "CONFIGURATION", configuration), redirect_stdout(output):
                    exit_code = main.main(["run", "review this", "--route", route, "--parallel"])

                self.assertEqual(exit_code, 2)
                self.assertIn("configured for sequential execution", output.getvalue())

    def test_prune_defaults_to_preview_and_deletes_only_on_apply(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflows_dir = root / "state" / "workflows"
            result_file = root / "results" / "old-result.json"
            result_file.parent.mkdir(parents=True)
            result_file.write_text("{}", encoding="utf-8")
            with patch.object(state_manager, "WORKFLOW_DIR", workflows_dir), patch.object(
                retention, "PROJECT_ROOT", root
            ):
                workflow = state_manager.create_workflow("old task", ["codex"])
                workflow["status"] = "SUCCESS"
                workflow["updated_at"] = "2020-01-01T00:00:00+00:00"
                workflow["agents"]["codex"]["status"] = "SUCCESS"
                workflow["agents"]["codex"]["result_file"] = str(result_file)
                workflow_file = state_manager.save_workflow(workflow)

                preview = retention.prune_completed_workflows(
                    older_than_days=30,
                    apply=False,
                )
                self.assertFalse(preview["applied"])
                self.assertTrue(workflow_file.exists())
                self.assertTrue(result_file.exists())

                applied = retention.prune_completed_workflows(
                    older_than_days=30,
                    apply=True,
                )

        self.assertTrue(applied["applied"])
        self.assertEqual(len(applied["deleted"]), 2)
        self.assertFalse(workflow_file.exists())
        self.assertFalse(result_file.exists())

    def test_prune_preserves_artifact_referenced_by_nonterminal_workflow(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflows_dir = root / "state" / "workflows"
            result_file = root / "results" / "shared.json"
            result_file.parent.mkdir(parents=True)
            result_file.write_text("{}", encoding="utf-8")
            with patch.object(state_manager, "WORKFLOW_DIR", workflows_dir), patch.object(
                retention, "PROJECT_ROOT", root
            ):
                old = state_manager.create_workflow("old task", ["codex"])
                old["status"] = "SUCCESS"
                old["updated_at"] = "2020-01-01T00:00:00+00:00"
                old["agents"]["codex"]["result_file"] = str(result_file)
                old_file = state_manager.save_workflow(old)

                active = state_manager.create_workflow("active task", ["codex"])
                active["agents"]["codex"]["result_file"] = str(result_file)
                active_file = state_manager.save_workflow(active)

                report = retention.prune_completed_workflows(
                    older_than_days=30,
                    apply=True,
                )
                self.assertEqual(len(report["deleted"]), 1)
                self.assertFalse(old_file.exists())
                self.assertTrue(active_file.exists())
                self.assertTrue(result_file.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
