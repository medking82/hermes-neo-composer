# Neo Composer

Ghost-text "next prompt" suggestions for Hermes Desktop, served by a small standalone service any client (Desktop, Forma, web UIs) can call.

**v0.5 aims to reduce upgrade breakage.** The archived v0.4.x integration targets a fixed Hermes release and requires a separately installed host patch. v0.5 uses the Desktop SDK and a standalone service; the only core change is the **optional** host adapter for strict image steer (see below), which is gated on file structure and anchors, never on a Hermes version number. Compatibility still needs checking after updates; future versions are not guaranteed.

| Part | Depends only on | When upstream changes |
|---|---|---|
| `service/neo_suggest.py` | Python stdlib + an OpenAI-compatible `/chat/completions` (Magpie) | Model groups are a candidate list with automatic fallback on 400/404/422, so a renamed Magpie group does not break it |
| `desktop-plugin/neo-composer/plugin.js` | the public `@hermes/plugin-sdk` (`COMPOSER_AREAS.underside`, `host.composer.setDraft`, `host.state.busyBySession`, `session.history` RPC) | In-box ghost text is a feature-detected enhancer; if it stops matching, the underside pill keeps working |
| `compat/smoke.py` | — | Run after every Hermes/Magpie update; FAIL = a required seam moved, WARN = only the in-box enhancer is affected |

The v0.4 code and README are kept under `legacy/v0.4/` for reference only.

## SDK-only catalog preview

[`catalog/`](catalog/README.md) is a separate unified plugin package (0.5.1 development preview) for future catalog review. It uses Hermes `ctx.llm` and public Desktop SDK contributions, with no standalone service, token-file access, DOM enhancer, core patch or self-updater. A catalog entry can select it with `subdir: catalog`. It adds per-session caching, explicit refresh, conservative output filters and draft-preserving acceptance. Choose its model through Desktop **Settings → Models → Auxiliary → Neo Composer**, using Hermes-configured providers rather than a required Magpie service.

The preview displays suggestions below the composer; in-input ghost text and strict steer await upstream SDK issues [#153327](https://github.com/NousResearch/hermes-agent/issues/153327) and [#153301](https://github.com/NousResearch/hermes-agent/issues/153301). Marketplace submission remains paused. See its README for installation, quota/data disclosures, compatibility and verification limits. The advanced distribution documented below remains available.


## Advanced Desktop: choose Hermes models

The advanced UI can use either **Hermes models** or the **standalone service**, preserving
in-box ghost text, Tab acceptance and strict steer in both modes. Install/update its
Python backend and Desktop UI together with Hermes' Python environment:

```sh
python deploy/install_desktop.py
```

The installer enables the backend using the official CLI (live gateway reload when
supported), and installs only the advanced Desktop UI. It refuses an existing unified
catalog package rather than overwriting its UI. It preserves service credentials and
host-adapter receipts. Re-run after pulling updates; this does not rebuild Hermes.

In Neo Composer settings choose **建議模型來源 → Hermes 已設定的模型**, then
**選擇 Hermes 模型** opens **Settings → Models → Auxiliary → Neo Composer**.
Select any provider/model already supported by Hermes. **Auto** follows Hermes' default
auxiliary routing. Use **重新產生建議** after changing models. **測試連線** in Hermes mode
makes one real prediction call with a small synthetic conversation (uses model quota).

Hermes mode sends at most eight recent user/assistant messages (2800 characters per
row) through the gateway's `plugin.neo-composer.predict` RPC to `ctx.llm` with task
`neo_composer`; credentials stay with Hermes. Cached candidate text remains in the
profile's plugin SQLite store for up to a day. Profile mismatches and missing RPCs
show errors without silently switching providers. Existing installations retain service
mode until changed in settings. The standalone service still supplies host-adapter
installation/control and remains available to external clients such as Forma.

## Interaction (Desktop)

- When the focused chat finishes a turn, the plugin reads the session history, asks the service, and shows one suggestion.
- **In the box:** an empty composer shows the suggestion as its grey placeholder; **Tab** fills it in (editable, never sent).
- **Below the box:** a pill with the same text — **click** fills the composer, **⧉** copies it, **✕** hides it.
- `Ctrl/Cmd+Shift+Enter` (rebindable) fills it in; palette command "Neo Composer: 重新產生建議" asks again.
- Settings ▸ Plugins ▸ Neo Composer: on/off, in-box on/off, service URL, optional token, connection test.

## Keys while a turn is running

| Key | Action |
|---|---|
| `Enter` | Queue the message for after the current turn (`busy=queue`, set per session) |
| `Ctrl/Cmd+Enter` (rebindable `steerKey`) | **Strict steer** into the running turn: text + image attachments |
| `Shift+Enter` | New line |

Strict steer never falls back. The draft and attachments are cleared only when the host returns a matching `delivered` receipt (same session, execution generation and request id). Without the host adapter, or on `not_delivered` / `rejected` / timeout / stale generation, the draft and attachments stay and a warning appears; nothing is queued, interrupted or redirected. Images are **not** sent as native multimodal input: the gateway stages the bytes under the profile `cache/images/` and the steer row references them for the model to read with `vision_analyze`.

## Host adapter (optional, one-click)

`host-adapter/` adds the `neo.composer.capabilities` / `neo.composer.steer` RPCs and the safe-boundary delivery hook (details in `host-adapter/README.md`). Install from Settings ▸ Plugins ▸ Neo Composer ▸ Host adapter: **Check** (dry run), **Install**, **Rollback**, **Finish installation and restart**. Opening the page never installs.

- The buttons call the local service (`/v1/host-adapter/{check,status,install,rollback,restart}`), which acts only on the configured `NEO_HERMES_ROOT`; the request can carry no path or command, mutations require `{"confirm": true}`, loopback client + Host, an allowed Origin (`NEO_CONTROL_ORIGINS`, default `null` + desktop dev origins) and a bearer `NEO_CONTROL_TOKEN` (falls back to `NEO_TOKEN`; no token → 503).
- Compatibility = required files/symbols exist, each anchor matches exactly once, patched Python parses. No version pins, so ordinary Hermes updates need no plugin update; a moved seam is **refused** and rolled back, and the plugin keeps working without strict steer.
- Backups go to `<root>/.neo-backups/<id>/`; files changed after install are not overwritten or deleted.
- On Windows the service generates a persistent control credential and shares it through `ctx.files.readText('data', 'control.json')`; no manual token is needed. Install acquires Hermes' checkout/build locks, patches the source, runs Hermes' own Windows `build` + `builder` into an isolated stage, and verifies the archive, Electron entry and renderer assets. No WSL is used by the install button. A build failure rolls back the new source patch and leaves the running package intact.
- After Check/Install reports a verified build waiting for exit, click **完成安裝並重啟** (Finish installation and restart). This force-closes this installation’s Desktop process tree, including active work; save drafts first. The authenticated service acknowledges the click, revalidates under the maintenance locks, then closes Desktop. You can also fully quit Hermes (including the tray) manually. The local service backs up and replaces the packaged resources, then reopens Hermes, which starts the updated gateway. It refuses staged or live file drift. Rollback cancels a pending install, or restores both source and the previous packaged resources at the next exit. Execution capability is checked separately; pending builds never count as enabled. Build details: `<hermes-root>/.neo-desktop-build.log`.
- After a Hermes update, run Check again; reinstall is idempotent.

## Service API (`neo-suggest-v1`)

```
GET  /healthz      -> {ok, version, contract, models, live_model, last_error, auth}
POST /v1/suggest   {"messages":[{"role":"user|assistant","content":"..."}]}
                   -> {suggestion: str|null, status: ready|empty|skipped|error, model, cached}
```

The last message must be from the assistant. Rows with images, data URLs or local paths are dropped before the model call. Suggestions that claim unobserved results ("我已經重啟了") or start with commit/push/deploy/delete/pay are rejected. Ready results are cached 6 h, empty ones 10 min, errors never. No conversation text is logged or stored. Configuration is environment variables (see the module docstring); `NEO_TOKEN` enables bearer auth, `NEO_CORS_ORIGINS` adds browser origins (loopback origins are always allowed).

## Deploy

**GA401 (or any Linux host with systemd linger), as the service user:**

```sh
curl -fsSL https://raw.githubusercontent.com/medking82/hermes-neo-composer/v0.5-durable/deploy/install.sh | sh
# or, from an existing checkout:  sh ~/services/neo-suggest/deploy/install.sh
```

It clones/fast-forwards `~/services/neo-suggest`, writes `~/.config/neo-suggest/env` once (loopback `127.0.0.1:3460`, upstream `127.0.0.1:3425/v1`, model `group/hestia`), installs the `neo-suggest` user unit plus an hourly `neo-suggest-compat.timer` (offline smoke check, no model call — `systemctl --user status neo-suggest-compat` shows FAIL after a breaking Hermes update), restarts and runs the smoke test. Re-run it to update.

**Windows PC:** every host runs its own service against its own local Magpie (no tunnel, no dependency on another machine). Clone a separate runtime checkout, start it hidden at login, and copy the plugin:

```sh
git clone -q --branch v0.5-durable https://github.com/medking82/hermes-neo-composer.git "$LOCALAPPDATA/hermes/services/neo-suggest"
# Startup folder launcher -> deploy/neo-suggest-windows.vbs (single instance, restarts on exit,
# uses %LOCALAPPDATA%\Python\bin\pythonw.exe, falls back to pyw.exe)
mkdir -p "$HERMES_HOME/desktop-plugins/neo-composer"
cp desktop-plugin/neo-composer/plugin.js "$HERMES_HOME/desktop-plugins/neo-composer/"
```

Update with `git -C "$LOCALAPPDATA/hermes/services/neo-suggest" pull --ff-only`, then end the `pythonw` process; the launcher restarts it automatically; after a forced kill Windows can hold the port for a minute or two, so allow ~2 min (a duplicate instance cannot grab the port).

Desktop hot-loads it. Do not bind the service to the LAN without `NEO_TOKEN`: it spends Magpie quota.

## Develop and test (WSL / Linux, Node 22, Python 3.12+)

```sh
python3 -m pytest -q service/test_neo_suggest.py service/test_host_control.py service/test_desktop_install.py host-adapter/test_neo_host_adapter.py
NEO_HERMES_TAR=<tar of Hermes HEAD> python3 -m pytest -q host-adapter/test_neo_host_adapter.py   # real-tree install/rollback
node --test desktop-plugin/plugin.test.mjs desktop-plugin/settings.test.mjs
python3 compat/smoke.py --hermes-src <hermes-agent checkout> --service http://127.0.0.1:3460 --live
```

Gateway regression tests for the adapter live in `host-adapter/tests/` (run against an isolated Hermes checkout; see its README). Development tests run in WSL/Linux. The user-authorized exception is the Neo install button's Windows Hermes packaging; GA401 is for deployment acceptance, never tests.

**Cleanup at the end of every task:** stop test gateways, fixture servers and probe services you started (check `ps`/listening ports in WSL and Windows), and delete scratch archives and temp dirs (`$HOME/neo-*`, `hermes-head.tar`, `neo-frontend-*`). Long-running services belong to systemd `--user` (Linux) or the Startup launcher (Windows), never to an ad-hoc background shell.

MIT license.
