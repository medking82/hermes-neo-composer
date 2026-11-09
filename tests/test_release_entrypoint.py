"""Offline entrypoint contracts using real local Git objects, never a deploy call."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.owner = self.home / "owner"
        self.runner = self.home / "runner"
        for repo in (self.owner, self.runner):
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "fixture@example.invalid")
            self.git(repo, "config", "user.name", "Release fixture")
        # An explicit fixture transport records arguments; it cannot run deployments.
        (self.runner / "release_qualification.py").write_text(
            "import json, pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "manifest = pathlib.Path(args[args.index('--manifest') + 1])\n"
            "timings = pathlib.Path(args[args.index('--timings') + 1])\n"
            "print(json.dumps({'args': args, 'manifest': json.loads(manifest.read_text()), "
            "'timings': json.loads(timings.read_text()), 'implementation': 'committed'}))\n"
        )
        (self.runner / "release_unittest.py").write_text("# fixture instrumentation\n")
        self.git(self.runner, "add", ".")
        self.git(self.runner, "commit", "-qm", "Fixture runner")
        self.pin = self.git(self.runner, "rev-parse", "HEAD")
        (self.owner / "scripts").mkdir()
        adapter = ROOT / "scripts" / "qualify_release.py"
        if adapter.exists():
            shutil.copy2(adapter, self.owner / "scripts" / adapter.name)
        self.config = {
            "runnerRevision": self.pin,
            "project": "fixture",
            "classShards": 2,
            "requireHermesSource": False,
            "manifest": {"scope": "full-offline", "suites": [{"name": "original"}]},
        }
        self.config_path = self.owner / "scripts" / "release-qualification.json"
        self.config_path.write_text(json.dumps(self.config))
        (self.owner / "scripts" / "release-class-timings.json").write_text('{"suites": []}')
        self.git(self.owner, "add", ".")
        self.git(self.owner, "commit", "-qm", "Fixture owner")

    def git(self, repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    def invoke(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(self.owner / "scripts" / "qualify_release.py"),
             "--runner-repo", str(self.runner), "--state", str(self.home / "state"), *args],
            text=True, capture_output=True,
            env={key: value for key, value in os.environ.items() if key != "HERMES_SOURCE"},
        )

    def test_executes_pinned_runner_and_committed_owner_manifest(self):
        self.config["manifest"]["suites"] = []
        self.config_path.write_text(json.dumps(self.config))
        (self.runner / "release_qualification.py").write_text("raise RuntimeError('dirty code executed')\n")
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["implementation"], "committed")
        self.assertEqual(evidence["manifest"]["suites"], [{"name": "original"}])
        self.assertEqual(evidence["timings"], {"suites": []})
        self.assertEqual(evidence["args"][evidence["args"].index("--commit") + 1],
                         self.git(self.owner, "rev-parse", "HEAD"))
        self.assertEqual(evidence["args"][evidence["args"].index("--class-shards") + 1], "2")

    def test_missing_pinned_objects_fail_without_running_dirty_files(self):
        self.config["runnerRevision"] = "0" * 40
        self.config_path.write_text(json.dumps(self.config))
        self.git(self.owner, "add", ".")
        self.git(self.owner, "commit", "-qm", "Unavailable pin")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unavailable locally", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_child_failure_is_propagated(self):
        (self.runner / "release_qualification.py").write_text("raise SystemExit(23)\n")
        self.git(self.runner, "add", ".")
        self.git(self.runner, "commit", "-qm", "Failing fixture runner")
        self.config["runnerRevision"] = self.git(self.runner, "rev-parse", "HEAD")
        self.config_path.write_text(json.dumps(self.config))
        self.git(self.owner, "add", ".")
        self.git(self.owner, "commit", "-qm", "Select failing runner")
        self.assertEqual(self.invoke().returncode, 23)

    def test_external_source_contract_cannot_be_silently_skipped(self):
        self.config["requireHermesSource"] = True
        self.config_path.write_text(json.dumps(self.config))
        self.git(self.owner, "add", ".")
        self.git(self.owner, "commit", "-qm", "Require external source")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set HERMES_SOURCE", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_external_source_reuse_is_rejected(self):
        self.config["requireHermesSource"] = True
        self.config_path.write_text(json.dumps(self.config))
        self.git(self.owner, "add", ".")
        self.git(self.owner, "commit", "-qm", "Require external source")
        source = self.home / "hermes-source"
        (source / "agent").mkdir(parents=True)
        for name in ("turn_context.py", "context_compressor.py"):
            (source / "agent" / name).write_text("# explicit source fixture\n")
        result = subprocess.run(
            [sys.executable, "-B", str(self.owner / "scripts" / "qualify_release.py"),
             "--runner-repo", str(self.runner), "--reuse"], text=True, capture_output=True,
            env=dict(os.environ, HERMES_SOURCE=str(source)),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Reuse is disabled", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_shared_runner_sibling_is_discovered_without_network(self):
        self.runner.rename(self.home / "hermes-fleet-sync")
        result = subprocess.run(
            [sys.executable, "-B", str(self.owner / "scripts" / "qualify_release.py"),
             "--state", str(self.home / "state")], text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["implementation"], "committed")

    def test_selected_owner_commit_controls_the_manifest(self):
        original = self.git(self.owner, "rev-parse", "HEAD")
        self.config["manifest"]["suites"] = [{"name": "new"}]
        self.config_path.write_text(json.dumps(self.config))
        self.git(self.owner, "add", ".")
        self.git(self.owner, "commit", "-qm", "New manifest")
        result = self.invoke("--commit", original, "--class-shards", "1", "--reuse")
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["manifest"]["suites"], [{"name": "original"}])
        self.assertIn("--reuse", evidence["args"])
        self.assertEqual(evidence["args"][evidence["args"].index("--class-shards") + 1], "1")


if __name__ == "__main__":
    unittest.main()
