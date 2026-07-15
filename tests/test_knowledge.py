from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tools.check_version_record import head_files
from workflow.codegraph import refresh_codegraph
from workflow.evidence import (
    EvidenceError,
    verify_signed_manifest,
    write_signed_manifest,
)
from workflow.knowledge import (
    KnowledgeError,
    KnowledgeVault,
    stitch_capability,
    task_requires_stitch,
)
from workflow.run import prepare_clone, run_gates, shared_prompt
from workflow.version_snapshot import (
    commit_snapshot_sha256,
    index_snapshot_sha256,
    worktree_snapshot_sha256,
)


READY_CAPABILITIES = {
    "route": "high",
    "required": ["agy", "codex", "claude", "git", "gitleaks", "codegraph"],
    "passed": True,
    "tools": {
        name: {
            "available": True,
            "exit_code": 0,
            "version": f"{name} test",
            "command": [name, "--version"],
        }
        for name in ("agy", "codex", "claude", "git", "gitleaks", "codegraph")
    },
}


class KnowledgeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("config", "user.name", "Knowledge Test")
        self._git("config", "user.email", "knowledge@example.invalid")
        (self.repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "-qm", "baseline")
        self.source_head = self._git_output("rev-parse", "HEAD").strip()
        self.spec = self.root / "TASK.md"
        self.spec.write_text("Update the value safely.\n", encoding="utf-8")
        self.vault = KnowledgeVault(self.root / "vault")

    def tearDown(self):
        self.temp.cleanup()

    def _git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def _git_output(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout

    def preflight(self, name: str = "knowledge-loop") -> dict:
        with mock.patch(
            "workflow.knowledge.assess_capabilities",
            return_value=json.loads(json.dumps(READY_CAPABILITIES)),
        ):
            return self.vault.prepare_task(
                repo=self.repo,
                route="high",
                task_name=name,
                spec=self.spec,
                acceptance=["python3 -m compileall -q app.py"],
                source_head=self.source_head,
                project_id="demo-project",
            )

    def test_preflight_updates_obsidian_vault_before_dispatch(self):
        preflight = self.preflight()
        self.assertTrue(preflight["ready"])
        self.assertEqual(preflight["current_version"], "0.0.0")
        self.assertEqual(preflight["planned_version"], "0.1.0")
        self.assertIn("python", preflight["languages"])
        self.assertTrue((self.vault.root / ".obsidian" / "app.json").is_file())
        self.assertTrue((self.vault.root / preflight["task_note"]).is_file())
        self.assertTrue(
            (self.vault.root / "Topics" / "Languages" / "python.md").is_file()
        )
        self.assertEqual(
            hashlib.sha256(preflight["briefing"].encode()).hexdigest(),
            preflight["briefing_sha256"],
        )
        for instruction in (
            "WORKFLOW_TASK.md",
            "SAGE_KNOWLEDGE.md",
            "codegraph explore",
            "human R5",
        ):
            self.assertIn(instruction, preflight["briefing"])

    def test_ui_task_fails_closed_without_stitch_design(self):
        self.spec.write_text(
            "Design a WPF desktop UI in XAML with a visual design system.\n",
            encoding="utf-8",
        )
        blocked = json.loads(json.dumps(READY_CAPABILITIES))
        blocked["tools"]["stitch"] = {
            "available": False,
            "exit_code": 1,
            "version": None,
            "command": ["stitch", "safe-capability-check"],
        }
        blocked["required"].append("stitch")
        blocked["passed"] = False
        with mock.patch("workflow.knowledge.assess_capabilities", return_value=blocked):
            preflight = self.vault.prepare_task(
                repo=self.repo,
                route="high",
                task_name="wpf-design",
                spec=self.spec,
                acceptance=["true"],
                source_head=self.source_head,
                project_id="demo-project",
            )
        self.assertFalse(preflight["ready"])
        self.assertTrue(preflight["stitch"]["required"])
        self.assertIn("Stitch DESIGN.md export", preflight["missing_knowledge"])
        self.assertIn("Topics/Tools/stitch.md", preflight["language_notes"])
        self.assertIn("Stitch design gate", preflight["briefing"])

    def test_policy_text_about_stitch_is_not_misclassified_as_ui_design(self):
        policy = (
            "Require Google Stitch before Web UI or WPF/XAML design and lock the "
            "export before Agent dispatch."
        )
        self.assertFalse(task_requires_stitch("policy-update", policy))
        self.assertTrue(
            task_requires_stitch(
                "customer-dashboard", "Design a Web UI dashboard with a sidebar."
            )
        )
        self.assertTrue(
            task_requires_stitch(
                "operator-dashboard",
                "Build a desktop visual UI for the operator dashboard.",
            )
        )
        self.assertTrue(
            task_requires_stitch(
                "operator-dashboard",
                "Desktop UI design for the operator dashboard.",
            )
        )
        self.assertTrue(
            task_requires_stitch(
                "operator-dashboard",
                "Build a WPF UI dashboard.\n"
                "Update the policy to lock the Stitch export.",
            )
        )
        self.assertTrue(
            task_requires_stitch(
                "operator-dashboard",
                "Update the desktop UI design using Stitch and lock the export.",
            )
        )
        self.assertTrue(
            task_requires_stitch(
                "operator-dashboard",
                "Restyle the desktop UI with new colors.",
            )
        )
        self.assertTrue(
            task_requires_stitch(
                "operator-dashboard",
                "Update using Stitch and lock the export, then implement the "
                "WPF UI redesign.",
            )
        )
        self.assertTrue(
            task_requires_stitch(
                "policy-and-dashboard-update",
                "Design a WPF UI dashboard.\nUpdate the Stitch policy to lock exports.",
            )
        )
        self.assertTrue(
            task_requires_stitch(
                "policy-and-dashboard-update",
                "WPF UI redesign for the operator console.\n"
                "Update the Stitch policy to lock exports.",
            )
        )
        self.assertTrue(
            task_requires_stitch(
                "policy-and-dashboard-update",
                "Require a locked Stitch export and a WPF UI redesign for the "
                "operator console.",
            )
        )

    def test_stitch_api_key_is_recognized_without_echoing_credential(self):
        with mock.patch.dict(
            "os.environ", {"STITCH_API_KEY": "secret-value"}, clear=True
        ):
            capability = stitch_capability(None, cwd=self.repo)
        self.assertTrue(capability["available"])
        self.assertEqual(capability["auth_mode"], "api_key")
        self.assertNotIn("secret-value", json.dumps(capability))

    def test_authenticated_stitch_mcp_with_schema_failure_is_not_ready(self):
        claude = mock.Mock(
            returncode=0,
            stdout=(
                "stitch: https://stitch.googleapis.com/mcp - "
                "! Connected · tools fetch failed\n"
            ),
        )
        codex = mock.Mock(returncode=0, stdout="Name Status Auth\n")
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch(
                "workflow.knowledge.shutil.which", return_value="/usr/bin/client"
            ),
            mock.patch(
                "workflow.knowledge.subprocess.run", side_effect=[claude, codex]
            ),
        ):
            capability = stitch_capability(None, cwd=self.repo)
        self.assertFalse(capability["available"])
        self.assertEqual(capability["status"], "authenticated_tools_unavailable")
        self.assertTrue(capability["mcp_clients"]["claude"]["authenticated"])
        self.assertFalse(capability["mcp_clients"]["claude"]["tools_ready"])

    def test_healthy_stitch_mcp_is_a_supported_auth_path(self):
        claude = mock.Mock(
            returncode=0,
            stdout="stitch: https://stitch.googleapis.com/mcp - ✔ Connected\n",
        )
        codex = mock.Mock(returncode=0, stdout="Name Status Auth\n")
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch(
                "workflow.knowledge.shutil.which", return_value="/usr/bin/client"
            ),
            mock.patch(
                "workflow.knowledge.subprocess.run", side_effect=[claude, codex]
            ),
        ):
            capability = stitch_capability(None, cwd=self.repo)
        self.assertTrue(capability["available"])
        self.assertEqual(capability["auth_mode"], "mcp_client")

    def test_success_distills_memory_and_forces_version_bump(self):
        preflight = self.preflight()
        run_dir = self.root / "run"
        run_dir.mkdir()
        self.vault.record_dispatch(
            preflight,
            run_dir=run_dir,
            codegraph={
                "passed": True,
                "action": "init",
                "files": 2,
                "nodes": 4,
                "edges": 3,
            },
        )
        result = self.vault.session(preflight, run_dir).complete(
            passed=True,
            checks={"acceptance_1": {"exit_code": 0}},
            stages=[
                {"agent": "agy", "exit_code": 0},
                {"agent": "codex", "exit_code": 0},
                {"agent": "claude", "exit_code": 0},
            ],
            changed_files=["app.py"],
            source_head=self.source_head,
        )
        self.assertTrue(result["memory_distilled"])
        self.assertTrue(result["version_bumped"])
        self.assertEqual(result["version"], "0.1.0")
        self.assertTrue(result["codegraph_current"])
        versions = (self.vault.root / "Projects" / "demo-project" / "Ver.md").read_text(
            encoding="utf-8"
        )
        memory = (
            self.vault.root / "Projects" / "demo-project" / "Memory.md"
        ).read_text(encoding="utf-8")
        self.assertIn("current_version: 0.1.0", versions)
        self.assertIn("## 0.1.0", versions)
        self.assertIn("Reuse this route and gate set", memory)
        task_note = (run_dir / "knowledge" / "task-note.md").read_text(encoding="utf-8")
        self.assertIn("Acceptance commands: 1 recorded by hash", task_note)
        for artifact in (
            "briefing.md",
            "task-note.md",
            "Memory.md",
            "Ver.md",
            "post-task.json",
        ):
            self.assertTrue((run_dir / "knowledge" / artifact).is_file())

    def test_nonzero_stage_cannot_advance_version(self):
        preflight = self.preflight("failed-stage")
        run_dir = self.root / "failed-stage"
        run_dir.mkdir()
        self.vault.record_dispatch(
            preflight,
            run_dir=run_dir,
            codegraph={
                "passed": True,
                "action": "init",
                "files": 1,
                "nodes": 1,
                "edges": 0,
            },
        )
        result = self.vault.session(preflight, run_dir).complete(
            passed=True,
            checks={"acceptance": {"exit_code": 0}},
            stages=[{"agent": "codex", "exit_code": 9}],
            changed_files=["app.py"],
            source_head=self.source_head,
        )
        self.assertFalse(result["version_bumped"])
        state = json.loads(
            (self.vault.root / "Projects" / "demo-project" / "State.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["current_version"], "0.0.0")
        self.assertEqual(state["history"][-1]["status"], "failed")

    def test_empty_candidate_cannot_advance_version(self):
        preflight = self.preflight("empty-candidate")
        run_dir = self.root / "empty-candidate"
        run_dir.mkdir()
        self.vault.record_dispatch(
            preflight,
            run_dir=run_dir,
            codegraph={
                "passed": True,
                "action": "init",
                "files": 1,
                "nodes": 1,
                "edges": 0,
            },
        )
        result = self.vault.session(preflight, run_dir).complete(
            passed=True,
            checks={"acceptance": {"exit_code": 0}},
            stages=[{"agent": "codex", "exit_code": 0}],
            changed_files=[],
            source_head=self.source_head,
        )
        self.assertFalse(result["version_bumped"])
        state = json.loads(
            (self.vault.root / "Projects" / "demo-project" / "State.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["current_version"], "0.0.0")

    def test_failed_task_is_remembered_without_advancing_version(self):
        successful = self.preflight("first")
        first_run = self.root / "first"
        first_run.mkdir()
        self.vault.record_dispatch(
            successful,
            run_dir=first_run,
            codegraph={
                "passed": True,
                "action": "init",
                "files": 1,
                "nodes": 1,
                "edges": 0,
            },
        )
        self.vault.session(successful, first_run).complete(
            passed=True,
            checks={"acceptance": {"exit_code": 0}},
            stages=[{"agent": "orchestrator", "exit_code": 0}],
            changed_files=["app.py"],
            source_head=self.source_head,
        )

        failed = self.preflight("second")
        second_run = self.root / "second"
        second_run.mkdir()
        self.vault.record_dispatch(
            failed,
            run_dir=second_run,
            codegraph={
                "passed": True,
                "action": "sync",
                "files": 1,
                "nodes": 1,
                "edges": 0,
            },
        )
        result = self.vault.session(failed, second_run).complete(
            passed=False,
            checks={"acceptance": {"exit_code": 1}},
            stages=[{"agent": "orchestrator", "exit_code": 0}],
            changed_files=[],
            source_head=self.source_head,
        )
        self.assertFalse(result["version_bumped"])
        self.assertEqual(result["version"], "0.1.0")
        state = json.loads(
            (self.vault.root / "Projects" / "demo-project" / "State.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["current_version"], "0.1.0")
        self.assertEqual(state["history"][-1]["status"], "failed")

    def test_concurrent_preflight_cannot_silently_overwrite_version(self):
        first = self.preflight("one")
        second = self.preflight("two")
        first_run = self.root / "one"
        second_run = self.root / "two"
        first_run.mkdir()
        second_run.mkdir()
        for preflight, run_dir in ((first, first_run), (second, second_run)):
            self.vault.record_dispatch(
                preflight,
                run_dir=run_dir,
                codegraph={
                    "passed": True,
                    "action": "sync",
                    "files": 1,
                    "nodes": 1,
                    "edges": 0,
                },
            )
        self.vault.session(first, first_run).complete(
            passed=True,
            checks={"acceptance": {"exit_code": 0}},
            stages=[{"agent": "orchestrator", "exit_code": 0}],
            changed_files=["app.py"],
            source_head=self.source_head,
        )
        with self.assertRaisesRegex(KnowledgeError, "concurrently"):
            self.vault.session(second, second_run).complete(
                passed=True,
                checks={"acceptance": {"exit_code": 0}},
                stages=[{"agent": "orchestrator", "exit_code": 0}],
                changed_files=["app.py"],
                source_head=self.source_head,
            )

    @unittest.skipUnless(shutil.which("codegraph"), "CodeGraph CLI is required")
    def test_clone_and_gates_force_codegraph_and_protect_shared_briefing(self):
        preflight = self.preflight()
        run_dir = self.root / "workflow-run"
        workspace = prepare_clone(
            self.repo,
            run_dir,
            self.spec,
            shared_briefing=preflight["briefing"],
        )
        codegraph = json.loads((run_dir / "codegraph.json").read_text(encoding="utf-8"))
        self.assertTrue(codegraph["passed"])
        self.assertTrue((workspace / ".codegraph" / "codegraph.db").is_file())
        contract = json.loads((run_dir / "contract.json").read_text(encoding="utf-8"))
        result = run_gates(
            workspace,
            contract,
            [
                'python3 -c "from pathlib import Path; '
                "assert 'VALUE' in Path('app.py').read_text()\""
            ],
            [],
            [],
            [],
        )
        self.assertTrue(result["checks"]["codegraph_current"]["exit_code"] == 0)
        self.assertTrue(result["passed"])
        (workspace / "SAGE_KNOWLEDGE.md").write_text("tampered\n", encoding="utf-8")
        tampered = run_gates(workspace, contract, ["true"], [], [], [])
        self.assertFalse(tampered["passed"])
        self.assertEqual(
            tampered["checks"]["shared_knowledge_contract"]["exit_code"], 1
        )

    @unittest.skipUnless(shutil.which("codegraph"), "CodeGraph CLI is required")
    def test_stitch_design_is_locked_before_ui_agent_dispatch(self):
        design = self.root / "DESIGN.md"
        design.write_text(
            "# Stitch design\n\nDesktop dashboard with an accessible sidebar.\n",
            encoding="utf-8",
        )
        run_dir = self.root / "stitch-run"
        workspace = prepare_clone(
            self.repo,
            run_dir,
            self.spec,
            stitch_design=design,
            stitch_required=True,
        )
        contract = json.loads((run_dir / "contract.json").read_text(encoding="utf-8"))
        self.assertTrue(contract["stitch_required"])
        locked = workspace / "STITCH_DESIGN.md"
        self.assertTrue(locked.is_file())
        passed = run_gates(workspace, contract, ["true"], [], [], [])
        self.assertEqual(passed["checks"]["stitch_design_contract"]["exit_code"], 0)
        locked.write_text("tampered\n", encoding="utf-8")
        failed = run_gates(workspace, contract, ["true"], [], [], [])
        self.assertEqual(failed["checks"]["stitch_design_contract"]["exit_code"], 1)
        self.assertFalse(failed["passed"])

    def test_every_agent_prompt_receives_shared_knowledge_directive(self):
        content = shared_prompt("Implement the task.")
        self.assertIn("SAGE_KNOWLEDGE.md", content)
        self.assertIn("CodeGraph", content)
        self.assertIn("Stitch", content)
        self.assertTrue(content.endswith("Implement the task."))

    def test_signed_evidence_covers_memory_and_version_snapshots(self):
        preflight = self.preflight("signed-memory")
        run_dir = self.root / "signed-run"
        run_dir.mkdir()
        self.vault.record_dispatch(
            preflight,
            run_dir=run_dir,
            codegraph={
                "passed": True,
                "action": "init",
                "files": 1,
                "nodes": 2,
                "edges": 1,
            },
        )
        knowledge = self.vault.session(preflight, run_dir).complete(
            passed=True,
            checks={"acceptance_1": {"exit_code": 0}},
            stages=[{"agent": "orchestrator", "exit_code": 0}],
            changed_files=["app.py"],
            source_head=self.source_head,
        )
        patch = run_dir / "final.patch"
        patch.write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
        result = {
            "schema_version": 1,
            "execution_kind": "agent_workflow",
            "name": "signed-memory",
            "route": "high",
            "automated_gates_passed": True,
            "r5_human_verification": "pending",
            "merge_authorized": False,
            "passed": True,
            "stages": [{"agent": "codex", "exit_code": 0}],
            "contract": {
                "source_repo": str(self.repo),
                "source_head": self.source_head,
            },
            "knowledge": knowledge,
            "final_gates": {
                "passed": True,
                "checks": {"acceptance_1": {"exit_code": 0}},
            },
            "promotion_manifest": {
                "final_patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
                "changed_files": ["app.py"],
                "acceptance_commands": ["true"],
            },
        }
        (run_dir / "result.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        key = self.root / "evidence-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            check=True,
        )
        allowed = self.root / "allowed_signers"
        allowed.write_text(
            "memory-test " + Path(f"{key}.pub").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        write_signed_manifest(run_dir, signing_key=key, signer_identity="memory-test")
        verified = verify_signed_manifest(run_dir, allowed_signers=allowed)
        self.assertIn("knowledge_artifacts_sha256", verified["artifacts"])
        memory = run_dir / "knowledge" / "Memory.md"
        memory.write_text(memory.read_text(encoding="utf-8") + "tamper\n")
        with self.assertRaisesRegex(EvidenceError, "artifact hashes"):
            verify_signed_manifest(run_dir, allowed_signers=allowed)


class CodeGraphLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("codegraph"), "CodeGraph CLI is required")
    def test_refresh_initializes_then_synchronizes_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "module.py").write_text("def answer():\n    return 42\n")
            first = refresh_codegraph(repo)
            second = refresh_codegraph(repo)
            self.assertTrue(first["passed"])
            self.assertEqual(first["action"], "init")
            self.assertTrue(second["passed"])
            self.assertEqual(second["action"], "sync")
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout
            self.assertEqual(status, "?? module.py\n")


class VersionRecordGateTests(unittest.TestCase):
    @staticmethod
    def _git(repo: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    @staticmethod
    def _run_version_check(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).resolve().parents[1] / "tools/check_version_record.py"
        return subprocess.run(
            [
                "python3",
                str(script),
                "--repo",
                str(repo),
                "--vault",
                "knowledge",
                "--project-id",
                "demo",
                "--require-head-update",
                *extra,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    @staticmethod
    def _run_staged_check(repo: Path) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).resolve().parents[1] / "tools/check_version_record.py"
        return subprocess.run(
            [
                "python3",
                str(script),
                "--repo",
                str(repo),
                "--vault",
                "knowledge",
                "--project-id",
                "demo",
                "--require-staged-update",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    @staticmethod
    def _write_demo_ledger(
        repo: Path, version: str, history: list[dict[str, object]]
    ) -> None:
        project = repo / "knowledge" / "Projects" / "demo"
        tasks = repo / "knowledge" / "Tasks" / "demo"
        project.mkdir(parents=True, exist_ok=True)
        tasks.mkdir(parents=True, exist_ok=True)
        successful = [item for item in history if item.get("version_bumped") is True]
        if successful:
            successful[-1]["candidate_tree_sha256"] = worktree_snapshot_sha256(repo)
        for index, item in enumerate(history):
            task_note = item.get("task_note")
            if not isinstance(task_note, str):
                raise AssertionError("test history requires a task note")
            task_id = Path(task_note).stem
            bumped = item.get("version_bumped") is True
            status = "automated_gates_passed" if bumped else "failed"
            item.setdefault("task_id", task_id)
            item.setdefault("task_name", task_id)
            item.setdefault("completed_at", f"2026-01-01T00:{index:02d}:00+00:00")
            item.setdefault("status", status)
            item.setdefault("route", "high")
            item.setdefault("source_head", "0" * 40)
            item.setdefault(
                "distilled_lesson",
                "Automated gates passed." if bumped else "Task failed closed.",
            )
            item.setdefault("briefing_sha256", "a" * 64)
            item.setdefault("changed_files", [])
        (project / "State.json").write_text(
            json.dumps(
                {"schema_version": 2, "current_version": version, "history": history}
            )
            + "\n",
            encoding="utf-8",
        )
        memory_entries = []
        version_entries = []
        for item in reversed(history):
            bumped = item["version_bumped"] is True
            memory_version = item["version"] if bumped else "unchanged"
            task_note = str(item["task_note"])
            task_link = Path(task_note).with_suffix("").as_posix()
            memory_entries.append(
                f"### {item['completed_at']} — {item['task_name']}\n\n"
                f"- Status: `{item['status']}`\n"
                f"- Route: `{item['route']}`\n"
                f"- Version: `{memory_version}`\n"
                f"- Lesson: {item['distilled_lesson']}\n"
                f"- Detail: [[{task_link}]]\n"
            )
            if bumped:
                changed = ", ".join(item["changed_files"]) or "none"
                candidate_tree_line = (
                    f"- Candidate tree: `{item['candidate_tree_sha256']}`\n"
                    if item.get("candidate_tree_sha256")
                    else ""
                )
                version_entries.append(
                    f"## {item['version']} — {item['completed_at']}\n\n"
                    f"- Task: [[{task_link}|{item['task_name']}]]\n"
                    f"- Source HEAD: `{item['source_head']}`\n"
                    f"- Route: `{item['route']}`\n"
                    f"- Changed: {changed}\n"
                    f"- Knowledge briefing: `{item['briefing_sha256']}`\n"
                    f"{candidate_tree_line}"
                )
        (project / "Memory.md").write_text(
            f"---\nproject: demo\ncurrent_version: {version}\n---\n"
            "# demo Memory\n\n" + "\n".join(memory_entries),
            encoding="utf-8",
        )
        (project / "Ver.md").write_text(
            f"---\nproject: demo\ncurrent_version: {version}\n"
            "version_policy: automatic_patch_after_successful_task\n---\n"
            "# demo Versions\n\n" + "\n".join(version_entries),
            encoding="utf-8",
        )
        for item in history:
            task_note = item.get("task_note")
            if isinstance(task_note, str):
                note = repo / "knowledge" / task_note
                note.parent.mkdir(parents=True, exist_ok=True)
                changed = ", ".join(item["changed_files"]) or "none yet"
                failing = "none" if item["version_bumped"] is True else "fixture"
                note.write_text(
                    "---\n"
                    f"task_id: {item['task_id']}\n"
                    "project: demo\n"
                    f"status: {item['status']}\n"
                    f"observed_at: {item['completed_at']}\n"
                    f"route: {item['route']}\n"
                    "---\n"
                    f"# {item['task_name']}\n\n"
                    "Project memory: [[Projects/demo/Memory]]\n"
                    "Version ledger: [[Projects/demo/Ver]]\n\n"
                    "## Contract\n\n"
                    f"- Source HEAD: `{item['source_head']}`\n\n"
                    "## Result\n\n"
                    f"- Changed files: {changed}\n"
                    f"- Failing checks: {failing}\n\n"
                    "## Distilled lesson\n\n"
                    f"{item['distilled_lesson']}\n",
                    encoding="utf-8",
                )

    def _create_merge_fixture(self, repo: Path, *, merge_only_update: bool) -> None:
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.name", "Merge Version Test")
        self._git(repo, "config", "user.email", "merge-version@example.invalid")
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        history = [
            {
                "version_bumped": True,
                "version": "0.1.0",
                "task_note": "Tasks/demo/task-0.1.0.md",
                "changed_files": ["app.py"],
            }
        ]
        self._write_demo_ledger(repo, "0.1.0", history)
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-qm", "baseline")

        self._git(repo, "switch", "-qc", "feature")
        (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        history.append(
            {
                "version_bumped": True,
                "version": "0.1.1",
                "task_note": "Tasks/demo/task-0.1.1.md",
                "changed_files": ["app.py"],
            }
        )
        self._write_demo_ledger(repo, "0.1.1", history)
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-qm", "versioned feature")
        self.assertEqual(self._run_version_check(repo).returncode, 0)

        self._git(repo, "switch", "-q", "main")
        reports = repo / "reports"
        reports.mkdir()
        (reports / "main.md").write_text("main history\n", encoding="utf-8")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-qm", "unversioned main report")
        if merge_only_update:
            self._git(repo, "merge", "--no-commit", "--no-ff", "feature")
            (repo / "merge_only.py").write_text("VALUE = 3\n", encoding="utf-8")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "merge with unsafe direct update")
        else:
            self._git(repo, "merge", "--no-ff", "-m", "merge feature", "feature")

    def test_candidate_digest_uses_git_clean_filter_bytes_for_crlf_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "CRLF Snapshot Test")
            self._git(repo, "config", "user.email", "crlf-snapshot@example.invalid")
            (repo / ".gitattributes").write_text(
                "*.ps1 text eol=crlf\n", encoding="utf-8"
            )
            script = repo / "script.ps1"
            script.write_text("Write-Output one\nWrite-Output two\n", encoding="utf-8")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "CRLF baseline")
            script.unlink()
            self._git(repo, "checkout", "--", "script.ps1")
            self.assertIn(b"\r\n", script.read_bytes())

            expected = commit_snapshot_sha256(repo, "HEAD")
            self.assertEqual(worktree_snapshot_sha256(repo), expected)
            self.assertEqual(index_snapshot_sha256(repo), expected)

    def test_first_staged_version_record_is_validated_before_initial_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Unborn Version Test")
            self._git(repo, "config", "user.email", "unborn-version@example.invalid")
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            history = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")

            checked = self._run_staged_check(repo)
            self.assertEqual(checked.returncode, 0, checked.stdout)
            self.assertIn('"current_version": "0.1.0"', checked.stdout)

    def test_merge_commit_revalidates_complete_first_parent_delta(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._create_merge_fixture(repo, merge_only_update=False)
            self.assertEqual(
                set(head_files(repo)),
                {
                    "app.py",
                    "knowledge/Projects/demo/Memory.md",
                    "knowledge/Projects/demo/State.json",
                    "knowledge/Projects/demo/Ver.md",
                    "knowledge/Tasks/demo/task-0.1.1.md",
                },
            )
            checked = self._run_version_check(repo)
            self.assertEqual(checked.returncode, 0, checked.stdout)

    def test_merge_commit_rejects_its_own_unversioned_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._create_merge_fixture(repo, merge_only_update=True)
            self.assertIn("merge_only.py", head_files(repo))
            checked = self._run_version_check(repo)
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("do not declare committed project changes", checked.stdout)

    def test_multicommit_pr_cannot_hide_unsafe_change_behind_reports_only_tip(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Range Test")
            self._git(repo, "config", "user.email", "range@example.invalid")
            history = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.strip()
            self._git(repo, "switch", "-qc", "feature")
            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            self._git(repo, "add", "app.py")
            self._git(repo, "commit", "-qm", "unsafe code")
            (repo / "reports").mkdir()
            (repo / "reports" / "tip.md").write_text("tail\n", encoding="utf-8")
            self._git(repo, "add", "reports/tip.md")
            self._git(repo, "commit", "-qm", "reports-only tip")
            checked = self._run_version_check(
                repo,
                "--base-ref",
                base,
                "--head-ref",
                "HEAD",
                "--comparison",
                "merge-base",
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("require a new successful version record", checked.stdout)

    def test_candidate_ledger_is_loaded_from_head_commit_not_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Snapshot Test")
            self._git(repo, "config", "user.email", "snapshot@example.invalid")
            history = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.strip()
            self._git(repo, "switch", "-qc", "feature")
            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            history.append(
                {
                    "version_bumped": True,
                    "version": "0.1.1",
                    "task_note": "Tasks/demo/task-0.1.1.md",
                    "changed_files": ["app.py"],
                }
            )
            self._write_demo_ledger(repo, "0.1.1", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "versioned feature")
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.strip()
            self._git(repo, "switch", "-q", "main")
            (repo / "knowledge" / "Projects" / "demo" / "State.json").write_text(
                "not the candidate ledger\n", encoding="utf-8"
            )
            checked = self._run_version_check(
                repo,
                "--base-ref",
                base,
                "--head-ref",
                head,
                "--comparison",
                "direct",
            )
            self.assertEqual(checked.returncode, 0, checked.stdout)
            self.assertIn('"current_version": "0.1.1"', checked.stdout)

    def test_staged_candidate_is_loaded_from_index_not_unstaged_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Index Snapshot Test")
            self._git(repo, "config", "user.email", "index-snapshot@example.invalid")
            history: list[dict[str, object]] = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")

            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            history.append(
                {
                    "version_bumped": True,
                    "version": "0.1.1",
                    "task_note": "Tasks/demo/task-0.1.1.md",
                    "changed_files": ["app.py"],
                }
            )
            self._write_demo_ledger(repo, "0.1.1", history)
            self._git(repo, "add", ".")
            project = repo / "knowledge" / "Projects" / "demo"
            (project / "State.json").write_text("not staged JSON\n", encoding="utf-8")

            checked = self._run_staged_check(repo)
            self.assertEqual(checked.returncode, 0, checked.stdout)
            self.assertIn('"staged_candidate_source": "index"', checked.stdout)
            self.assertIn('"current_version": "0.1.1"', checked.stdout)

    def test_staged_decoy_cannot_borrow_valid_unstaged_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Index Decoy Test")
            self._git(repo, "config", "user.email", "index-decoy@example.invalid")
            history: list[dict[str, object]] = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")

            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            project = repo / "knowledge" / "Projects" / "demo"
            staged_state = {
                "current_version": "0.1.0",
                "history": history,
                "decoy": True,
            }
            (project / "State.json").write_text(
                json.dumps(staged_state) + "\n", encoding="utf-8"
            )
            (project / "Memory.md").write_text(
                "---\ncurrent_version: 0.1.0\n---\n# staged decoy\n",
                encoding="utf-8",
            )
            (project / "Ver.md").write_text(
                "---\ncurrent_version: 0.1.0\n---\n## 0.1.0\n# staged decoy\n",
                encoding="utf-8",
            )
            decoy_note = repo / "knowledge" / "Tasks" / "demo" / "task-0.1.1.md"
            decoy_note.write_text("# staged placeholder\n", encoding="utf-8")
            self._git(
                repo,
                "add",
                "app.py",
                "knowledge/Projects/demo/State.json",
                "knowledge/Projects/demo/Memory.md",
                "knowledge/Projects/demo/Ver.md",
                "knowledge/Tasks/demo/task-0.1.1.md",
            )

            history.append(
                {
                    "version_bumped": True,
                    "version": "0.1.1",
                    "task_note": "Tasks/demo/task-0.1.1.md",
                    "changed_files": ["app.py"],
                }
            )
            self._write_demo_ledger(repo, "0.1.1", history)
            checked = self._run_staged_check(repo)
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn(
                "staged project changes require a new successful version record",
                checked.stdout,
            )

    def test_failed_history_requires_memory_and_task_note_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Failed History Test")
            self._git(repo, "config", "user.email", "failed-history@example.invalid")
            history: list[dict[str, object]] = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.strip()
            history.append(
                {
                    "task_id": "missing-failed-task",
                    "task_name": "missing-failed-task",
                    "completed_at": "2026-01-01T01:00:00+00:00",
                    "status": "failed",
                    "route": "high",
                    "source_head": base,
                    "version": None,
                    "version_bumped": False,
                    "changed_files": [],
                    "distilled_lesson": "Task failed closed.",
                    "task_note": "Tasks/demo/missing-failed-task.md",
                }
            )
            state = repo / "knowledge" / "Projects" / "demo" / "State.json"
            state.write_text(
                json.dumps({"current_version": "0.1.0", "history": history}) + "\n",
                encoding="utf-8",
            )
            self._git(repo, "add", str(state.relative_to(repo)))
            self._git(repo, "commit", "-qm", "unbacked failed history")
            checked = self._run_version_check(
                repo, "--base-ref", base, "--head-ref", "HEAD"
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("missing required ledger file", checked.stdout)

    def test_ver_frontmatter_cannot_be_spoofed_by_body_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Frontmatter Test")
            self._git(repo, "config", "user.email", "frontmatter@example.invalid")
            history: list[dict[str, object]] = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.strip()
            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            history.append(
                {
                    "version_bumped": True,
                    "version": "0.1.1",
                    "task_note": "Tasks/demo/task-0.1.1.md",
                    "changed_files": ["app.py"],
                }
            )
            self._write_demo_ledger(repo, "0.1.1", history)
            version_file = repo / "knowledge" / "Projects" / "demo" / "Ver.md"
            spoofed = version_file.read_text(encoding="utf-8").replace(
                "current_version: 0.1.1", "current_version: 0.1.0", 1
            )
            version_file.write_text(
                spoofed.replace(
                    "# demo Versions",
                    "<!-- current_version: 0.1.1 -->\n# demo Versions",
                    1,
                ),
                encoding="utf-8",
            )
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "spoofed frontmatter")
            checked = self._run_version_check(
                repo, "--base-ref", base, "--head-ref", "HEAD"
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("Ver.md current_version does not match", checked.stdout)

    def test_empty_memory_or_task_note_cannot_satisfy_context_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Empty Context Test")
            self._git(repo, "config", "user.email", "empty-context@example.invalid")
            history: list[dict[str, object]] = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.strip()
            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            history.append(
                {
                    "version_bumped": True,
                    "version": "0.1.1",
                    "task_note": "Tasks/demo/task-0.1.1.md",
                    "changed_files": ["app.py"],
                }
            )
            self._write_demo_ledger(repo, "0.1.1", history)
            note = repo / "knowledge" / "Tasks" / "demo" / "task-0.1.1.md"
            note.write_text("", encoding="utf-8")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "empty task note")
            checked = self._run_version_check(
                repo, "--base-ref", base, "--head-ref", "HEAD"
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("missing YAML frontmatter", checked.stdout)

    def test_knowledge_only_staged_candidate_is_validated_from_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Knowledge Index Test")
            self._git(repo, "config", "user.email", "knowledge-index@example.invalid")
            history: list[dict[str, object]] = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")
            state = repo / "knowledge" / "Projects" / "demo" / "State.json"
            state.write_text("{ invalid staged json\n", encoding="utf-8")
            self._git(repo, "add", str(state.relative_to(repo)))
            state.write_text(
                subprocess.run(
                    ["git", "show", "HEAD:knowledge/Projects/demo/State.json"],
                    cwd=repo,
                    text=True,
                    stdout=subprocess.PIPE,
                    check=True,
                ).stdout,
                encoding="utf-8",
            )
            checked = self._run_staged_check(repo)
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("staged candidate State.json is invalid JSON", checked.stdout)

    def test_multiple_sequential_records_cover_range_by_union(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Union Test")
            self._git(repo, "config", "user.email", "union@example.invalid")
            history: list[dict[str, object]] = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["a.py"],
                }
            ]
            (repo / "a.py").write_text("A = 1\n", encoding="utf-8")
            (repo / "b.py").write_text("B = 1\n", encoding="utf-8")
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.strip()
            (repo / "a.py").write_text("A = 2\n", encoding="utf-8")
            history.append(
                {
                    "version_bumped": True,
                    "version": "0.1.1",
                    "task_note": "Tasks/demo/task-0.1.1.md",
                    "changed_files": ["a.py"],
                }
            )
            self._write_demo_ledger(repo, "0.1.1", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "version one")
            (repo / "b.py").write_text("B = 2\n", encoding="utf-8")
            history.append(
                {
                    "version_bumped": True,
                    "version": "0.1.2",
                    "task_note": "Tasks/demo/task-0.1.2.md",
                    "changed_files": ["b.py"],
                }
            )
            self._write_demo_ledger(repo, "0.1.2", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "version two")
            checked = self._run_version_check(
                repo,
                "--base-ref",
                base,
                "--head-ref",
                "HEAD",
            )
            self.assertEqual(checked.returncode, 0, checked.stdout)

    def test_staged_and_committed_project_updates_require_all_memory_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.name", "Version Test"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "version@example.invalid"],
                cwd=repo,
                check=True,
            )
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            history = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task.md",
                    "changed_files": ["app.py"],
                }
            ]
            self._write_demo_ledger(repo, "0.1.0", history)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)

            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            script = (
                Path(__file__).resolve().parents[1] / "tools/check_version_record.py"
            )
            staged = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--repo",
                    str(repo),
                    "--vault",
                    "knowledge",
                    "--project-id",
                    "demo",
                    "--require-staged-update",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertNotEqual(staged.returncode, 0)
            self.assertIn("require a new successful version record", staged.stdout)

            subprocess.run(
                ["git", "commit", "-qm", "unsafe update"], cwd=repo, check=True
            )
            committed = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--repo",
                    str(repo),
                    "--vault",
                    "knowledge",
                    "--project-id",
                    "demo",
                    "--require-head-update",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertNotEqual(committed.returncode, 0)
            self.assertIn("require a new successful version record", committed.stdout)

    def test_later_commit_cannot_reuse_recorded_filename_with_different_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Tree Binding Test")
            self._git(repo, "config", "user.email", "tree@example.invalid")
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            history = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout.strip()
            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            history.append(
                {
                    "version_bumped": True,
                    "version": "0.1.1",
                    "task_note": "Tasks/demo/task-0.1.1.md",
                    "changed_files": ["app.py"],
                }
            )
            self._write_demo_ledger(repo, "0.1.1", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "versioned change")
            (repo / "app.py").write_text("VALUE = 999\n", encoding="utf-8")
            self._git(repo, "add", "app.py")
            self._git(repo, "commit", "-qm", "same-path tamper")

            checked = self._run_version_check(repo, "--base-ref", base)
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("tree does not match", checked.stdout)

    def test_type_change_and_rename_source_are_versioned_changes(self):
        for attack in ("type-change", "rename-into-reports"):
            with (
                self.subTest(attack=attack),
                tempfile.TemporaryDirectory() as temporary,
            ):
                repo = Path(temporary)
                self._git(repo, "init", "-q", "-b", "main")
                self._git(repo, "config", "user.name", "Path Delta Test")
                self._git(repo, "config", "user.email", "path@example.invalid")
                (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
                history = [
                    {
                        "version_bumped": True,
                        "version": "0.1.0",
                        "task_note": "Tasks/demo/task-0.1.0.md",
                        "changed_files": ["app.py"],
                    }
                ]
                self._write_demo_ledger(repo, "0.1.0", history)
                self._git(repo, "add", ".")
                self._git(repo, "commit", "-qm", "baseline")
                if attack == "type-change":
                    (repo / "app.py").unlink()
                    (repo / "app.py").symlink_to("missing.py")
                    self._git(repo, "add", "app.py")
                else:
                    (repo / "reports").mkdir()
                    self._git(repo, "mv", "app.py", "reports/app.py")

                staged = self._run_staged_check(repo)
                self.assertNotEqual(staged.returncode, 0)
                self.assertIn("require a new successful version record", staged.stdout)
                self._git(repo, "commit", "-qm", attack)
                committed = self._run_version_check(repo)
                self.assertNotEqual(committed.returncode, 0)
                self.assertIn(
                    "require a new successful version record", committed.stdout
                )

    def test_existing_knowledge_context_cannot_be_hollowed_out(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.name", "Context Retention Test")
            self._git(repo, "config", "user.email", "context@example.invalid")
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            history = [
                {
                    "version_bumped": True,
                    "version": "0.1.0",
                    "task_note": "Tasks/demo/task-0.1.0.md",
                    "changed_files": ["app.py"],
                }
            ]
            self._write_demo_ledger(repo, "0.1.0", history)
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "baseline")
            (repo / "knowledge" / "Tasks" / "demo" / "task-0.1.0.md").unlink()
            project = repo / "knowledge" / "Projects" / "demo"
            (project / "Memory.md").write_text(
                "---\nproject: demo\ncurrent_version: 0.1.0\n---\n# demo Memory\n",
                encoding="utf-8",
            )
            (project / "Ver.md").write_text(
                "---\nproject: demo\ncurrent_version: 0.1.0\n---\n"
                "# demo Versions\n\n## 0.1.0\n",
                encoding="utf-8",
            )
            script = (
                Path(__file__).resolve().parents[1] / "tools/check_version_record.py"
            )
            worktree = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--repo",
                    str(repo),
                    "--vault",
                    "knowledge",
                    "--project-id",
                    "demo",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertNotEqual(worktree.returncode, 0)
            self._git(repo, "add", "-A")
            self.assertNotEqual(self._run_staged_check(repo).returncode, 0)
            self._git(repo, "commit", "-qm", "hollow knowledge")
            self.assertNotEqual(self._run_version_check(repo).returncode, 0)
