# Offline release qualification

Run this local step before publishing or installing a Neo `v0.5-durable` revision, including a service update or copying the Desktop plugin. Use native WSL/Linux Python 3.12+ and Node 22; the runner stages the committed source into a temporary Linux checkout. Dirty and untracked files are excluded. Commit intended changes before qualifying them.

```sh
# In WSL, from the intended Neo checkout under /mnt/c/GitHub:
mkdir -p "$HOME/release-qualification"
python3 -B scripts/qualify_release.py \
  --state "$HOME/release-qualification/neo" \
  > "$HOME/release-qualification/neo-latest.json"
```

The command prints the exact owner commit and shared runner revision to stderr. Exit zero means every declared offline suite passed. Keep the output and per-suite logs private. The output filename alone does not prove success; inspect the exit status and the receipt's `result` and `commit` before using it as local evidence. A failed run can still produce a receipt.

`scripts/release-qualification.json` pins the shared runner at `medking82/hermes-fleet-sync` commit `4f79a5b4452d9a91037e4cbf564a927b44e2bac6`. The adapter searches ancestor sibling checkouts named `hermes-release-opt` and `hermes-fleet-sync`, or accepts `--runner-repo /path/to/existing/checkout`. It reads the pinned runner and instrumentation with `git show`; it never runs dirty shared files, fetches, installs dependencies, or edits that checkout. Missing pinned objects fail with an actionable error. An available local checkout containing that revision is a prerequisite.

The selected owner commit supplies its own manifest and stable placement file, also read with `git show`. `--commit FULL_SHA` qualifies another committed revision containing these files. The manifest preserves all five existing checks: service unittest discovery, plugin syntax, plugin Node tests, Python compilation, and installer shell syntax. It additionally runs the adapter regression suite. Service discovery includes future `test*.py` files. `legacy/v0.4` is archived on this branch and is outside this gate; the separate older `origin/main` v0.4 release lane is not qualified by this command.

Every unittest suite emits measured class durations, collected test IDs and occurrence indexes, executed counts, skips and failures. The default remains serial: short-suite measurements did not justify enabling workers. To evaluate whole-class weighted placement explicitly:

```sh
python3 -B scripts/qualify_release.py --class-shards 2 \
  --state "$HOME/release-qualification/neo" \
  > "$HOME/release-qualification/neo-two-workers.json"
```

The committed `scripts/release-class-timings.json` contains measured WSL placement hints. Unknown classes always run; obsolete weights never select tests. The shared planner verifies disjoint and complete collected occurrences while keeping classes whole. Class fixtures are included in class timing; module fixtures and startup remain in wall time. Node and syntax suites retain their existing commands and suite durations.

Refresh placement only as an explicit reviewed change: run once with `--class-shards 1`, extract sanitized class IDs and durations into the placement file, then commit it. A prior receipt can be supplied with `--timings /path/to/stable-placement-receipt.json`. Keep that input stable and distinct from output receipts; overwriting it after every run changes qualification identity and defeats reuse.

`--reuse` opts into fresh, identical local offline evidence. It preserves the original run ID only when source, manifest, runner, environment, workers, placement hints and log/report hashes agree. Use the same invocation and placement input on repeats. These unsigned local receipts are not accepted by any production controller and cannot bypass installation, runtime acceptance, or existing release guards.

The public GitHub Checks workflow retains every existing check, expands service discovery, and runs the adapter contracts on pushes and PRs. It does not have access to the private shared runner repository, so full shared qualification remains the explicit local WSL command above. No new network dependency or CI secret is required. CI success alone is not a shared qualification receipt.

`deploy/install.sh` remains the remote installation/update and health/smoke lane. Its timer runs compatibility smoke after installation; it does not rerun the offline release suite. Windows runtime updates and Desktop plugin copies likewise follow local qualification. The installer currently defaults to `main`; this adapter does not change that branch selection. Choose the intended revision/branch through the existing deployment process and separately verify what was installed. No installation, restart, live model probe or deployment is performed by qualification.
