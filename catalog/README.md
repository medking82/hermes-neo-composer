# Neo Composer — SDK-only preview

This package provides grounded next-message candidates below the Hermes Desktop composer. It is a development preview for a future catalog submission, not a marketplace listing. The existing GitHub release v0.5.0 contains the advanced distribution; this package is version 0.5.1 and has not been released as a tag.

## Use

Install the `catalog` subdirectory from this repository:

```sh
hermes plugins install 'medking82/hermes-neo-composer#catalog'
hermes plugins enable neo-composer
```

Then enable Neo Composer in Desktop's Capabilities → Plugins. Both the Python plugin and its Desktop half must be enabled. If generation reports that the RPC is unavailable, restart the gateway to load the Python half. Hermes 0.23.1 or newer is required, and the gateway must advertise `plugin-rpc-v1`; the UI checks this capability before generating.

The advanced standalone plugin has the same ID. Use one distribution at a time: disable the advanced copy before enabling this package and remove that standalone copy before installing the unified Desktop half. Installing this preview does not stop a separately installed `neo-suggest` service or roll back a host adapter; manage those through the advanced distribution's controls if you no longer need them.

After a turn completes, a candidate appears below the composer. Click its text to insert it as an editable draft, or choose Copy, Dismiss or Refresh. The command palette also offers **Neo Composer: refresh candidate**. The accept action is rebindable and has no default shortcut. Accept never sends a message.

Acceptance requires the same focused session, an idle turn, unchanged enabled settings and a confirmed empty draft. An unavailable editor (`null`) is refused. The final operation uses the SDK's `insertText`, so typing that races the earlier emptiness check is preserved; in that narrow case the candidate can be inserted alongside the new text. The public SDK does not provide an atomic empty-draft acceptance operation.

## Package boundaries

This directory is self-contained. A future catalog entry can select it with `subdir: catalog`; the service, host adapter and archived integration in the repository root are outside the installed package.

| Capability | This SDK-only package | Advanced distribution |
| --- | --- | --- |
| Candidate below the composer, refresh/copy/dismiss | Yes | Yes |
| Model access | Hermes `ctx.llm`, active host model | Separate local service |
| In-input ghost text and Tab acceptance | Awaiting upstream SDK [#153327](https://github.com/NousResearch/hermes-agent/issues/153327) | DOM enhancer |
| Strict steer with delivery receipts | Awaiting upstream SDK [#153301](https://github.com/NousResearch/hermes-agent/issues/153301) | Optional host adapter |
| Core patching, rebuilds, credential files, self-updater | None | See advanced README |

The package uses public SDK contributions, `ctx.rest`, a registered plugin RPC, and profile-scoped `plugin_db` storage. It does not query app DOM, intercept browser keys, replace Hermes functions, launch a daemon, read token files or update itself. Built-in Enter/Ctrl+Enter behaviour is unchanged. Generation is refused when the focused session's profile differs from the active gateway profile.

Candidates use an original prompt and conservative output filters adapted from this repository's prediction service. The filters reject known patterns for unobserved completion claims and commit/push/deploy/publish/delete/payment requests. These patterns reduce bad predictions; they do not prove that every accepted suggestion is correct. A script-based language guard follows the latest decisive user message: it distinguishes Latin, Han, Kana and Hangul, but cannot distinguish all languages that share a script. Short ambiguous strings may pass.

## Data and quota disclosure

- Automatic generation after a completed turn or focus change, and explicit Refresh, can use your active Hermes model quota. Cached or dismissed candidates for an unchanged excerpt are reused until expiry unless you refresh.
- Up to eight recent user/assistant text rows, at most 2,800 characters each, are sent through Hermes to its configured model provider. Tool rows are excluded. There is no plugin-specific external endpoint or telemetry.
- Candidate text, a transcript hash, request identifiers and settings are stored in the active profile's `plugin-data/neo-composer/data.db`. The transcript excerpt is not persisted by this plugin. A hash is a content fingerprint, not encryption.
- Candidates expire after one day and expired rows are deleted on the next database access. Inactive installations can retain expired bytes longer; this is not a scheduled deletion guarantee. The store keeps at most 200 sessions. Hermes may retain provider or host logs according to its own settings.
- Disabling suggestions invalidates pending results. New turns and newer requests invalidate older candidates. No shell commands, permanent background processes, separate credentials or model/provider overrides are used.

## Validation

Run in WSL/Linux from this directory with FastAPI and HTTPX available in the test environment:

```sh
python3 -m unittest discover -s tests -v
node --check desktop/plugin.js
node --test tests/plugin.test.mjs
hermes plugins validate .
```

Node tests require `node:module.registerHooks` (Node 22.15 or newer). The Python runtime uses Hermes-provided FastAPI/Pydantic and SQLite; HTTPX is test-only. Tests cover cross-process persistence, stale generation, disable/re-enable, input validation, output filtering, session/profile changes and draft preservation. Frontend tests use an SDK stub. Validation is a technical admission check; real Desktop interaction and a live host-model request remain separate acceptance steps.

Market submission remains paused. A future submission still needs a reviewed full commit SHA, truthful capability declarations, screenshots from the real UI and maintainer review of differentiation from existing suggestion plugins.

MIT License — see [LICENSE](LICENSE).
