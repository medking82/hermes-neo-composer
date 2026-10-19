# Neo Composer

A standalone Hermes Desktop plugin for session-bound suggestions, with an official-SDK compatibility mode and an optional native enhancement. The host retains editing, focus and send ownership; model routing, settings and persistence live here.

**Development candidate: public host-SDK prediction.** Missing strict Steering no longer disables suggestions. On an owner-aware official draft SDK, use the **Neo Composer · Suggestions** status-bar button to preview and explicitly **Insert As Draft**. This mode does not supply native gray text or Tab/Esc arbitration and never sends. Predictions use the host's public `ctx.llm` API, not a pinned Hermes commit or private transport. Missing required API capabilities disable prediction without blocking official Hermes updates. Native suggestions require behavior v2; Neo busy-key overrides additionally require strict receipts v1.

The **legacy optional native adaptation only** targets Desktop `3752497cc4d214023f4736559a5f0e58621af9ff` with its separately verified backend. Those fingerprints are not requirements for SDK prediction or a reason to hold Hermes at an old version. See [upgrade resilience and local setup](docs/upgrade-resilience.md). The [9e01b44 adaptation](docs/compatibility-desktop-9e01b44.md) is historical and is not interchangeable. The [existing upstream seam proposal](https://github.com/NousResearch/hermes-agent/pull/139051) remains separate and unmerged; no upstream acceptance is assumed.

## SDK Compatibility Mode

### Independent Compatibility Boundaries

- Profile-owned settings remain available when a prediction or native adapter is incompatible; connection/profile ownership and stale-scope checks still apply. An unavailable public host catalog is omitted rather than bypassed.
- Prediction checks public SDK capabilities and uses a plugin-owned `neo_next_prompt` auxiliary task. It does not read host source hashes, construct provider clients, or open credential contents. The old `prediction_pins` metadata is historical, not a prediction runtime gate. The original native `pins` inventory remains unchanged for the separate legacy enhancement.
- The host owns credentials, request construction, trust checks, retries and configured fallback routes. This prediction-only policy replaces the former private single-attempt/fixed-destination adapter; it does not change the main conversation or global model settings. The selected prediction route is a task default; an operator's native `auxiliary.neo_next_prompt` override takes precedence.
- Source revisions in validation records identify tested snapshots, not an install/runtime lock or a promise that every future SDK is compatible. Frontend build identity and the owning backend identity must be verified independently. This adaptation does not port native gray text, key overrides or reliable Steering.
- Verification is isolated SDK/backend contract testing, not a claim that a live plugin was installed or reloaded. An incompatible prediction adapter can pause predictions without removing the settings needed to disable or repair it.

Open **Neo Composer · Suggestions** in the status bar while the focused chat is idle and its draft is empty. Preview, insert as a draft, dismiss or refresh explicitly. Closing the popover stops its controller. Connection/profile/session changes and a changed draft refuse stale insertion; a consumed decision is recorded only after the SDK acknowledges the write. Before insertion, a non-generating `/validate` read checks the current owned session version, prediction route and ready request identity; a stale result clears the local offer without recording a dismissal or scheduling new inference. The stored session model configuration contributes only an opaque version input, including endpoint/policy-reference changes with unchanged model names; its contents are neither returned nor sent as prediction history. This is a freshness check at the validation boundary, not an atomic lock against every later user action. Native shortcuts are untouched. The status-bar surface is deliberate: ordinary composer slots do not expose an owner-qualified per-surface context.

The SDK frontend and backend must come from the same verified package: a missing `/validate` endpoint makes the SDK frontend refuse insertion rather than silently skip the check. An official update is not permission to restore an old renderer patch. API availability is checked separately from actual inference and visible client acceptance.

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

Automatic selection ranks eligible host-approved text models only when billing provenance and fresh comparable USD metadata are explicit. It does not treat subscriptions as free or infer billing from a provider name or token prefix. Hosts that omit billing provenance show unknown cost: select an explicit low-cost fallback or model instead. This chooses the primary task default; the host's configured retry/fallback policy may use another route. Refresh catalogs in Hermes model settings; availability metadata is not an inference guarantee.

The plugin never changes the main chat's model, provider, Fast mode or reasoning effort. Predictions default to low effort on their own auxiliary task and make one logical text-only SDK request, with no tools, auto-send or new credentials. Host-managed retries and configured fallbacks are permitted for prediction; native auxiliary settings can override its task defaults. The suggestion wait deadline does not cancel an already-admitted synchronous host call. That call retains the single per-profile execution slot until it physically completes; late results are not published. New contexts are skipped while the slot is occupied, not queued or retried by the plugin. A suggestion is not authorization to act.

### Deliberately unsupported sources

Unauthenticated, user-defined/custom, explicitly unavailable and malformed host catalog rows are not offered as primary prediction choices. Authentication and inheritance remain the host's responsibility, not a plugin-private credential parser. Unknown billing stays unknown. Required SDK changes fail closed for prediction; settings and unrelated editor functions remain independent. This is capability-based support, not a guarantee for every future release.

## Install and upgrade

This repository is a unified agent-plugin package (`plugin.yaml`, Python backend and `desktop/plugin.js`). Install through Hermes' existing plugin flow, explicitly enable the backend and the Desktop half, and select prediction settings. On a split PC/backend installation, the Python package belongs on the backend host; the Desktop half belongs in that PC's resolved Desktop plugin directory. Never copy credentials between hosts.

**The host seam is optional for SDK mode and required for the full native interaction.** The fixed-release installers under `host/installer/` provide backend and Windows Desktop check/apply/rollback, with frozen preimages and verified backups. Follow [installation, uninstall and official upgrades](docs/install-uninstall.md). `host/v0.22.2-strict.patch` remains the developer source diff against exact release `d923a5eb487a17c0a68801bba9ef0f56c81040a8`, not a force installer. The plugin itself never modifies core files; its settings explicitly launch a separately selected local installer through the SDK OS door. New independent enhancement bundles preserve the base SDK plugin during install and uninstall. The host bundle never replaces the Electron executable, ASAR, main or preloads. Official upgrades remain owned by the official updater: uninstall the host patch first, upgrade normally, and only then use an explicitly compatible replacement bundle.

Back up the previous package and renderer controls. Refuse unknown native edits/version drift, preserve the existing Electron executable and main/preload, and retain a hash-bound rollback. The validated native deployment uses per-machine private manifests; those contain local paths and are intentionally not published. Do not regenerate a native install manifest against an unknown modified target. Disable a native enhancement before changing its host version; SDK mode does not require holding Hermes at an older commit. A newly installed Python package may require a controlled backend restart; reloading Desktop plugins alone does not prove backend activation.

Before any shared-runtime switch, notify other affected task owners and confirm safe pause checkpoints before controlled backend and client restarts. A queued notification alone is not pause confirmation. See [v0.22.2 validation](docs/compatibility-v0.22.2.md) for evidence and limits. The older host patch is retained only for historical releases, not for this package version.

## Develop and test

Use the Hermes-managed Python environment for imports; no standalone dependency resolver is shipped.

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
