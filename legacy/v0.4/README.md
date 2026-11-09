# Neo Composer

A standalone Hermes Desktop plugin for persistent, session-bound ghost-text suggestions and predictable busy-turn keys. The host retains native editing, focus and send ownership; model routing, settings and persistence live here.

**Compatibility:** **0.4.5** targets Hermes **v0.22.2**, with the separate, explicitly installed **composer behavior v2 + strict steering receipts v1** host seam. It is **not plug-and-play on an unmodified official Desktop build**. Unknown backend interfaces fail closed. An upstream seam proposal is separate from this plugin; no merge is implied.

## Interaction

- After a completed turn, an empty, focused composer may show a suggestion. This is not as-you-type autocomplete.
- **Tab** accepts it as an editable, undoable draft. It does not send.
- **Esc** persistently dismisses that candidate/context.
- **Enter** sends when idle and queues while busy.
- **Ctrl+Enter** while busy requests strict `session.steer`. It accepts text plus up to four local PNG/JPEG/WEBP images through a separate staging-only route. Other attachments, unsupported hosts, unavailable vision tools, compression and ended turns retain the draft with an explicit notice; there is no redirect, interrupt or next-turn fallback.
- “Waiting for safe-boundary delivery”, “Steering injected” and the next-turn queue are distinct states. The composer clears only the unchanged submitted draft after its matching delivery receipt—not after the RPC's buffer acknowledgement. A delivery receipt confirms insertion into the conversation, not that the model has read or acted on it. Disconnects and unconfirmed delivery retain the draft and do not automatically retry.
- Images use **reference + the session's existing vision tool**, not native multimodal Steering. The success notice means reference injection only; it does not claim the model has inspected the image. Text and thumbnails clear together only for the matching request and ordered image-reference batch. Prediction excludes image references, payloads and private-path lines.
- **Shift+Enter** inserts a newline.
- A cached empty prediction re-asks itself once after ten minutes on the next idle trigger; user decisions (Tab-accept, Esc) are never re-asked. Typing, attachments, IME and native completion UI retain priority. Refresh/reconnect does not intentionally repeat inference for the same persisted context.

## Prediction settings

Open **Settings ▸ Plugins → Neo Composer**. On hosts that predate the unified plugin settings surface, the plugin keeps its previous sidebar entry as a fallback so the settings stay reachable. Prediction is **off by default** and no provider is pre-approved. Enable only providers you already use, then choose automatic selection or an explicit model.

Automatic selection ranks eligible, account-bound text models by comparable verified API prices. It does not treat subscriptions as free or compare subscription quotas with API dollars. If comparable pricing is unavailable, it uses only your explicitly chosen low-cost fallback; otherwise prediction remains off with an explanation. An explicit model never silently falls back. Catalog metadata is read-only and must be fresh; refresh models in Hermes itself when necessary. Availability metadata is not an inference guarantee.

The plugin never changes the main chat's model, provider, Fast mode or reasoning effort. Predictions use an independent low-effort, bounded, text-only request, with no tools, auto-send, provider retry ladder or new credentials. A suggestion is not authorization to act.

### Deliberately unsupported sources

Unbound legacy API-key catalog aliases, root-borrowed account identities, ambiguous credential mixtures, macOS Anthropic Keychain identities and relocated Claude credential directories not represented in the host fingerprint are excluded or treated as unknown billing. Custom endpoints and changed host interfaces require separate validation. Do not loosen these checks merely to make a model appear.

## Install and upgrade

This repository is a unified agent-plugin package (`plugin.yaml`, Python backend and `desktop/plugin.js`). Install through Hermes' existing plugin flow, explicitly enable the backend and the Desktop half, and select prediction settings. On a split PC/backend installation, the Python package belongs on the backend host; the Desktop half belongs in that PC's resolved Desktop plugin directory. Never copy credentials between hosts.

**Install the host seam separately first.** The fixed-release installers under `host/installer/` provide backend and Windows Desktop check/apply/rollback, with frozen preimages and verified backups. Follow [installation, uninstall and official upgrades](docs/install-uninstall.md). `host/v0.22.2-strict.patch` remains the developer source diff against exact release `d923a5eb487a17c0a68801bba9ef0f56c81040a8`, not a force installer. The plugin itself never modifies core files; the host bundle never replaces the Electron executable, ASAR, main or preloads. Official upgrades remain owned by the official updater: uninstall the host patch first, upgrade normally, and only then use an explicitly compatible replacement bundle.

Back up the previous package and renderer controls. Refuse unknown edits/version drift, preserve the existing Electron executable and main/preload, and retain a hash-bound rollback. The validated deployment uses per-machine private manifests; those contain local paths and are intentionally not published. Do not regenerate an install manifest against an unknown modified target. Disable the prediction setting before changing host versions. The current backend does not remount an already mounted Python API router: a controlled backend restart may be needed; reloading Desktop plugins alone does not prove backend activation.

Before any shared-runtime switch, notify other affected task owners and confirm safe pause checkpoints before controlled backend and client restarts. A queued notification alone is not pause confirmation. See [v0.22.2 validation](docs/compatibility-v0.22.2.md) for evidence and limits. The older host patch is retained only for historical releases, not for this package version.

## Develop and test

Use the pinned Hermes environment for Python imports; no standalone dependency resolver is shipped.

```sh
python run-tests.py
node --test plugin/controller.test.mjs
python build-plugin.py
```

`build-plugin.py` deterministically creates `dist/plugin.js`; copy the verified output to `desktop/plugin.js` when preparing a release. Its only runtime imports are the Hermes plugin SDK and the host's React.

The v0.4.3 validation record covers backend unit/integration contracts, native Desktop composer tests, TypeScript, repository checks, Windows build, idempotent install/rollback and foreign-edit refusal. Its browser fixture uses real Composer, prompt actions and steering handler; inference and tool execution are deterministic substitutes. A separate real subscription-backed prediction on synthetic input succeeded without changing main configuration; cache reuse was verified by deterministic service/browser tests.

The image-Steering implementation was installed and accepted in the real Windows Desktop window as **0.4.5-rc.1**: native busy Ctrl+Enter delivered the image reference, the original agent actually read its pixels through `vision_analyze`, the matching receipt cleared text and thumbnail together, explicit rejection retained both without queue fallback, and ordinary Enter later arrived as a separate user turn with zero images. **0.4.5 changes only version metadata, generated plugin version/hash and documentation; host behavior, renderer and installers are unchanged.** The installed RC identity and rollback receipts were not relabelled or reinstalled for publication. This is not native multimodal Steering or a guarantee of automatic image inspection. Full regression results remain non-green: 87 Python failures, 250 setup errors and 2 UI failures were matched to the fixed baseline/environment; blocked test bodies remain unexercised. See [validation and remaining limits](docs/validation-0.4.5.md) and [the strict-Steering and image contract](docs/strict-steering.md). Unknown dirty packaged shells still require independently verified, explicitly approved native fingerprints; never regenerate trust from arbitrary dirty bytes.

## Related work

The interaction is substantially similar to [#137560](https://github.com/NousResearch/hermes-agent/pull/137560) and [#70970](https://github.com/NousResearch/hermes-agent/pull/70970). Those proposals implement suggestions in core (including deterministic extraction and, in #137560, optional prediction). This project instead keeps policy/persistence/model selection in an independent plugin and proposes only a native, versioned contribution seam. [#44081](https://github.com/NousResearch/hermes-agent/pull/44081) concerns a one-shot session-start CLI suggestion API. [#121383](https://github.com/NousResearch/hermes-agent/pull/121383) also overlaps the queue/steer keyboard experience, but implements a core busy-input-mode setting rather than this plugin contribution. No uniqueness claim is made for ghost text, Tab acceptance or queue/steer shortcuts.

## Illustrations and evidence

The two concepts below were generated through the existing ChatGPT image-generation integration; the settings explanatory copy was corrected manually. They are not runtime screenshots and the exact underlying image-model brand is not asserted.

![Settings concept — not a runtime screenshot](docs/images/settings-concept.png)
![Workflow concept — not a runtime screenshot](docs/images/workflow-concept.png)

This is a real rendering of the plugin settings in an isolated browser fixture with a deterministic provider catalog, **not the current Desktop window**:

![Real isolated settings fixture](docs/images/settings-fixture.png)

MIT license. No private configuration, account fingerprints, credentials or machine deployment logs are included.
