# Neo Composer

A standalone Hermes Desktop plugin for session-bound suggestions, with an official-SDK compatibility mode and an optional native enhancement. The host retains editing, focus and send ownership; model routing, settings and persistence live here.

**Candidate: 0.5.0-rc.1.** Missing strict Steering no longer disables suggestions. On an owner-aware official draft SDK, use the **Neo Composer · Suggestions** status-bar button to preview and explicitly **Insert As Draft**. This mode does not supply native gray text or Tab/Esc arbitration and never sends. Native suggestions require behavior v2; Neo busy-key overrides additionally require strict receipts v1. Prediction still needs a compatible backend and explicit provider settings; unknown backend interfaces fail closed.

The current native adaptation targets Desktop `3752497cc4d214023f4736559a5f0e58621af9ff`, with the existing pinned backend. See [upgrade resilience and local setup](docs/upgrade-resilience.md). The [9e01b44 adaptation](docs/compatibility-desktop-9e01b44.md) is historical and is not interchangeable. The [existing upstream seam proposal](https://github.com/NousResearch/hermes-agent/pull/139051) remains separate and unmerged; no upstream acceptance is assumed.

## SDK Compatibility Mode

### Independent Compatibility Boundaries

- Profile-owned settings remain available when a prediction or native adapter is incompatible; connection/profile ownership and stale-scope checks still apply. An unavailable private-interface catalog is omitted rather than read without validation.
- Prediction checks its own closed, 12-file private-interface inventory in `prediction_pins`. Unknown prediction bytes still fail closed. The original 21-file `pins` inventory is retained unchanged for the version-bound native context; native/Steering-only drift is not a prerequisite for SDK predictions.
- The additional official helper variant is not an automatic hash refresh: it matches the exact `d923a5e` Git blob, differs from the previously pinned helper only in two Steering definitions, and leaves prediction/cache/socket helpers and module-level globals unchanged. Routing, credential, endpoint and retry checks are unchanged.
- PC Desktop `b406d1860b9a3865926cad3a4348f4f854466ae7` exposes the owner-aware draft SDK, but the observed GA401 serve still imports the separate `d923a5e` checkout. Neither identity proves the other. This recovery does not port native gray text, key overrides or reliable Steering to the new Desktop.
- Verification is isolated SDK/backend contract testing, not a claim that a live plugin was installed or reloaded. An incompatible prediction adapter can pause predictions without removing the settings needed to disable or repair it.

Open **Neo Composer · Suggestions** in the status bar while the focused chat is idle and its draft is empty. Preview, insert as a draft, dismiss or refresh explicitly. Closing the popover stops its controller. Connection/profile/session changes and a changed draft refuse stale insertion; a consumed decision is recorded only after the SDK acknowledges the write. Before insertion, a non-generating `/validate` read checks the current owned session version, prediction route and ready request identity; a stale result clears the local offer without recording a dismissal or scheduling new inference. The stored session model configuration contributes only an opaque version input, including endpoint/policy-reference changes with unchanged model names; its contents are neither returned nor sent as prediction history. This is a freshness check at the validation boundary, not an atomic lock against every later user action. Native shortcuts are untouched. The status-bar surface is deliberate: ordinary composer slots do not expose an owner-qualified per-surface context.

The SDK frontend and backend must come from the same recovery commit: a missing `/validate` endpoint makes the SDK frontend refuse insertion rather than silently skip the check. PC's observed pending update `2e83e2a935ee04f606aab58e498d34ca58d84c07` leaves the composer SDK and the twelve prediction seam files unchanged relative to `b406d18`. Its owning-profile model-selection change was inspected separately; this does not certify that newer backend on GA401 or claim a live upgrade was applied.

## Native Interaction — Enhancement Required

These shortcuts describe the full native enhancement with a verified strict backend, not SDK compatibility mode. With behavior v2 but no strict interface, suggestions remain registered and Neo key overrides are omitted.

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

**The host seam is optional for SDK mode and required for the full native interaction.** The fixed-release installers under `host/installer/` provide backend and Windows Desktop check/apply/rollback, with frozen preimages and verified backups. Follow [installation, uninstall and official upgrades](docs/install-uninstall.md). `host/v0.22.2-strict.patch` remains the developer source diff against exact release `d923a5eb487a17c0a68801bba9ef0f56c81040a8`, not a force installer. The plugin itself never modifies core files; its settings explicitly launch a separately selected local installer through the SDK OS door. New independent enhancement bundles preserve the base SDK plugin during install and uninstall. The host bundle never replaces the Electron executable, ASAR, main or preloads. Official upgrades remain owned by the official updater: uninstall the host patch first, upgrade normally, and only then use an explicitly compatible replacement bundle.

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

### Historical Validation

The v0.4.3 validation record covers backend unit/integration contracts, native Desktop composer tests, TypeScript, repository checks, Windows build, idempotent install/rollback and foreign-edit refusal. Its browser fixture uses real Composer, prompt actions and steering handler; inference and tool execution are deterministic substitutes. A separate real subscription-backed prediction on synthetic input succeeded without changing main configuration; cache reuse was verified by deterministic service/browser tests.

The image-Steering implementation was installed and accepted in the real Windows Desktop window as **0.4.5-rc.1**: native busy Ctrl+Enter delivered the image reference, the original agent actually read its pixels through `vision_analyze`, the matching receipt cleared text and thumbnail together, explicit rejection retained both without queue fallback, and ordinary Enter later arrived as a separate user turn with zero images. **0.4.5 changes only version metadata, generated plugin version/hash and documentation; host behavior, renderer and installers are unchanged.** The installed RC identity and rollback receipts were not relabelled or reinstalled for publication. This is not native multimodal Steering or a guarantee of automatic image inspection. Full regression results remain non-green: 87 Python failures, 250 setup errors and 2 UI failures were matched to the fixed baseline/environment; blocked test bodies remain unexercised. See [validation and remaining limits](docs/validation-0.4.5.md) and [the strict-Steering and image contract](docs/strict-steering.md). Unknown dirty packaged shells still require independently verified, explicitly approved native fingerprints; never regenerate trust from arbitrary dirty bytes.

## Related work

The interaction is substantially similar to [#137560](https://github.com/NousResearch/hermes-agent/pull/137560) and [#70970](https://github.com/NousResearch/hermes-agent/pull/70970). Those proposals implement suggestions in core (including deterministic extraction and, in #137560, optional prediction). This project instead keeps policy/persistence/model selection in an independent plugin and proposes only a native, versioned contribution seam. [#44081](https://github.com/NousResearch/hermes-agent/pull/44081) concerns a one-shot session-start CLI suggestion API. [#121383](https://github.com/NousResearch/hermes-agent/pull/121383) also overlaps the queue/steer keyboard experience, but implements a core busy-input-mode setting rather than this plugin contribution. No uniqueness claim is made for ghost text, Tab acceptance or queue/steer shortcuts.

## Illustrations and evidence

The two concepts below were generated through the existing ChatGPT image-generation integration; the settings explanatory copy was corrected manually. They are not runtime screenshots and the exact underlying image-model brand is not asserted.

![Settings concept — not a runtime screenshot](docs/images/settings-concept.png)
![Workflow concept — not a runtime screenshot](docs/images/workflow-concept.png)

This historical 0.4.x image is a real rendering of the plugin settings in an isolated browser fixture with a deterministic provider catalog, **not the current Desktop window**:

![Real isolated settings fixture](docs/images/settings-fixture.png)

MIT license. No private configuration, account fingerprints, credentials or machine deployment logs are included.
