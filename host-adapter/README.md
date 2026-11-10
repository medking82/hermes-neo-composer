# Neo host adapter (strict steer + images, contract protocol 1)

Gate = **structure + contract**, never the Hermes release number. Unknown future layouts are *refused*, not guessed.

- Backend (`gateway/neo_composer_adapter.py`): RPCs `neo.composer.capabilities` / `neo.composer.steer`. Generation-fenced; text + image bytes (staged, referenced for `vision_analyze`); delivered only at the pre-request tool boundary; timeout withdraws atomically; receipt = request_id + session + generation + image_count.
- Hook points (anchors, marker `neo-composer:strict-steer:v1`): `gateway/session_controls.py` (handler registration), `agent/turn_iteration_prep.py` (boundary delivery). Frontend (source checkouts only): `sdk/composer.ts` (`steerStrict`), `use-composer-submit.ts`, `neo-strict-steer.ts`.
- Plugin feature-detects `host.composer.steerStrict`; absent/failed → draft + attachments kept, no queue/interrupt fallback.

## Install from Neo Composer

Open Settings → Plugins → Neo Composer → Host adapter, then click **Install**.
The PC service automatically provisions the control token in the plugin's private
SDK data folder. It acquires Hermes' own update/build locks, backs up and applies
the structure-checked patch, and runs the installed Windows Hermes build scripts
into a separate staging directory. The install path does not depend on WSL.

After archive, Electron entry and renderer asset verification succeeds, fully quit
Hermes (including the tray). The service swaps in the verified resources, preserves
the previous resources for rollback, and reopens Hermes. It never kills the current
conversation. Do not reopen manually during the handoff. Source/resource drift is
refused. **Rollback** cancels a pending installation or schedules the saved package
for the next exit, together with restoring the source. Build failures restore the
new source patch and leave the running resources untouched.

The settings status distinguishes staged / awaiting exit from installed, and
checks running SDK/RPC capabilities separately. Log: `.neo-desktop-build.log` in
the Hermes checkout. MSIX-only installations without a writable source checkout
are not supported by this optional adapter.

## Installer CLI (source only)
```
python3 host-adapter/neo_host_adapter.py check     --root <hermes-agent>   # dry run
python3 host-adapter/neo_host_adapter.py install   --root <hermes-agent> [--frontend auto|skip|require]
python3 host-adapter/neo_host_adapter.py rollback  --root <hermes-agent> [--id ID]
python3 host-adapter/neo_host_adapter.py uninstall --root <hermes-agent>
```
Or via `deploy/install.sh` with `NEO_HERMES_ROOT=<hermes-agent>` (opt-in; refusal never breaks the plugin install).
Backups: `<root>/.neo-backups/<id>/`. Install is idempotent, rolls back on any failure, refuses ambiguous (anchor ≠ 1 match), partial, or unparsable results.
Restart the gateway after install; the desktop frontend needs a rebuild for the source patches.

## Tests
`NEO_HERMES_TAR=<tar of Hermes HEAD> pytest host-adapter/test_neo_host_adapter.py`
