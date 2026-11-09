# Neo Composer

Ghost-text "next prompt" suggestions for Hermes Desktop, served by a small standalone service any client (Desktop, Forma, web UIs) can call.

**v0.5 aims to reduce upgrade breakage.** The archived v0.4.x integration targets a fixed Hermes release and requires a separately installed host patch. v0.5 uses the Desktop SDK and a standalone service without a core patch. Compatibility still needs checking after updates; future versions are not guaranteed.

| Part | Depends only on | When upstream changes |
|---|---|---|
| `service/neo_suggest.py` | Python stdlib + an OpenAI-compatible `/chat/completions` (Magpie) | Model groups are a candidate list with automatic fallback on 400/404/422, so a renamed Magpie group does not break it |
| `desktop-plugin/neo-composer/plugin.js` | the public `@hermes/plugin-sdk` (`COMPOSER_AREAS.underside`, `host.composer.setDraft`, `host.state.busyBySession`, `session.history` RPC) | In-box ghost text is a feature-detected enhancer; if it stops matching, the underside pill keeps working |
| `compat/smoke.py` | — | Run after every Hermes/Magpie update; FAIL = a required seam moved, WARN = only the in-box enhancer is affected |

The v0.4 code and README are kept under `legacy/v0.4/` for reference only.

## Interaction (Desktop)

- When the focused chat finishes a turn, the plugin reads the session history, asks the service, and shows one suggestion.
- **In the box:** an empty composer shows the suggestion as its grey placeholder; **Tab** fills it in (editable, never sent).
- **Below the box:** a pill with the same text — **click** fills the composer, **⧉** copies it, **✕** hides it.
- `Ctrl/Cmd+Shift+Enter` (rebindable) fills it in; palette command "Neo Composer: 重新產生建議" asks again.
- Settings ▸ Plugins ▸ Neo Composer: on/off, in-box on/off, service URL, optional token, connection test.

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
curl -fsSL https://raw.githubusercontent.com/medking82/hermes-neo-composer/main/deploy/install.sh | sh
# or, from an existing checkout:  sh ~/services/neo-suggest/deploy/install.sh
```

It clones/fast-forwards `~/services/neo-suggest`, writes `~/.config/neo-suggest/env` once (loopback `127.0.0.1:3460`, upstream `127.0.0.1:3425/v1`, model `group/hestia`), installs the `neo-suggest` user unit, restarts and runs the smoke test. Re-run it to update.

**PC:** the service stays on GA401; forward it with SSH (`-L 127.0.0.1:3460:127.0.0.1:3460 ga401`) and copy the plugin:

```sh
mkdir -p "$HERMES_HOME/desktop-plugins/neo-composer"
cp desktop-plugin/neo-composer/plugin.js "$HERMES_HOME/desktop-plugins/neo-composer/"
```

Desktop hot-loads it. Do not bind the service to the LAN without `NEO_TOKEN`: it spends Magpie quota.

## Develop and test (WSL / Linux, Node 22, Python 3.12+)

```sh
(cd service && python3 -m unittest -v test_neo_suggest)
node --test desktop-plugin/plugin.test.mjs
python3 compat/smoke.py --hermes-src <hermes-agent checkout> --service http://127.0.0.1:3460 --live
```

MIT license.
