#!/usr/bin/env python3
"""Qualify an exact owner commit offline with the pinned shared Linux runner.

No fetch, install, deployment or production receipt acceptance is performed here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def gitdir(repo):
    marker = Path(repo).resolve() / ".git"
    if marker.is_file():
        value = marker.read_text().strip().removeprefix("gitdir: ")
        # Windows-created linked worktrees use a drive path in their .git marker.
        if re.match(r"^[A-Za-z]:[/\\]", value):
            value = "/mnt/" + value[0].lower() + "/" + value[3:].replace("\\", "/")
        marker = (marker.parent / value).resolve()
    if not marker.is_dir():
        raise ValueError(f"Expected an available local Git checkout: {repo}")
    return marker


def git(repo, *args):
    return subprocess.check_output(
        ["git", "--git-dir=" + str(gitdir(repo)), *args], stderr=subprocess.PIPE
    )


def linux_storage(path):
    resolved = Path(path).expanduser().resolve()
    if re.match(r"^/mnt/[a-z](?:/|$)", str(resolved)):
        raise ValueError("Qualification state and temporary workspaces must use the Linux filesystem")
    return resolved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-repo", type=Path, help="Existing shared runner checkout; never fetched")
    parser.add_argument("--commit", default="HEAD", help="Committed owner source to qualify (default HEAD)")
    parser.add_argument("--state", type=Path, help="Private Linux evidence directory")
    parser.add_argument("--class-shards", type=int, choices=range(1, 33))
    parser.add_argument("--timings", type=Path, help="Prior receipt for placement only; default committed measurements")
    parser.add_argument("--reuse", action="store_true", help="Opt in to identical local offline evidence reuse")
    parser.add_argument("--max-age", type=float, default=86400)
    args = parser.parse_args(argv)
    if sys.platform != "linux":
        parser.error("Run with native Linux Python inside WSL/Linux")
    try:
        linux_storage(tempfile.gettempdir())
        commit = git(ROOT, "rev-parse", "--verify", args.commit + "^{commit}").decode().strip()
        config = json.loads(git(ROOT, "show", commit + ":scripts/release-qualification.json"))
        revision = config["runnerRevision"]
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("runnerRevision must pin a full Git commit ID")
        state = linux_storage(args.state or Path.home() / ".local/state/release-qualification" / config["project"])
        if config.get("requireHermesSource"):
            source = Path(os.environ.get("HERMES_SOURCE", "/nonexistent"))
            for relative in ("agent/turn_context.py", "agent/context_compressor.py"):
                if not (source / relative).is_file():
                    raise ValueError("Set HERMES_SOURCE to an available Hermes source checkout; release checks must not skip it")
            if args.reuse:
                raise ValueError("Reuse is disabled for external Hermes source contracts; run them each time")
        candidates = [args.runner_repo] if args.runner_repo else [
            parent / name for parent in ROOT.parents
            for name in ("hermes-release-opt", "hermes-fleet-sync")
        ]
        files = ("release_qualification.py", "release_unittest.py")
        snapshots = None
        for candidate in candidates:
            try:
                snapshots = {name: git(candidate, "show", revision + ":" + name) for name in files}
                break
            except (ValueError, subprocess.CalledProcessError):
                continue
        if snapshots is None:
            raise ValueError(f"Pinned shared runner {revision} unavailable locally; provide --runner-repo CHECKOUT (no automatic fetch)")
        with tempfile.TemporaryDirectory(prefix="owner-release-runner-") as directory:
            staging = Path(directory)
            for name, content in snapshots.items():
                (staging / name).write_bytes(content)
            manifest = staging / "manifest.json"
            manifest.write_text(json.dumps(config["manifest"]))
            timings = staging / "timings.json"
            timings.write_bytes(git(ROOT, "show", commit + ":scripts/release-class-timings.json"))
            command = [sys.executable, "-B", str(staging / "release_qualification.py"),
                       "--repo", str(ROOT), "--commit", commit, "--manifest", str(manifest),
                       "--state", str(state), "--class-shards", str(args.class_shards or config["classShards"]),
                       "--timings", str(args.timings.resolve() if args.timings else timings),
                       "--max-age", str(args.max_age)]
            if args.reuse:
                command.append("--reuse")
            print(f"Offline qualification: owner={commit} shared-runner={revision}", file=sys.stderr)
            return subprocess.run(command, check=False).returncode
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.error(f"Offline qualification unavailable: {error}")


if __name__ == "__main__":
    raise SystemExit(main())
