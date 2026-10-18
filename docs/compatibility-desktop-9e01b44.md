# Desktop Compatibility: `9e01b44dd23978f9ff40b7837467f3a9f1582130`

This is a **candidate Desktop-only adaptation**, not evidence of a live installation. The plugin remains **0.4.5**; its controller, backend, credentials and prediction settings are unchanged.

## Exact Split-Host Boundary

- Desktop baseline: Hermes `9e01b44dd23978f9ff40b7837467f3a9f1582130`.
- Backend baseline: the existing strict-Steering deployment on `d923a5eb487a17c0a68801bba9ef0f56c81040a8`, with the exact backend fingerprints in `host-compat.json`. This adaptation does **not** patch or upgrade that backend.
- Source patch: [`../host/v0.22.2-desktop-9e01b44.patch`](../host/v0.22.2-desktop-9e01b44.patch).
- Source/patch identities: [`../host/desktop-9e01b44-candidate.json`](../host/desktop-9e01b44-candidate.json).
- Required host capabilities remain composer behavior **v2** and strict Steering receipts **v1**. A matching visible `v0.22.2` label alone is insufficient.

The prior `host/v0.22.2-strict.patch` remains bound to its original `d923a5eb...` baseline. Do not apply it directly to this newer Desktop, force a failed patch, or merely bypass the capability check.

## Preserved Behavior

The adaptation retains the newer native queue, busy-input modes, submission ownership and interrupted-message finalization. Native Steering without a strict receipt id keeps the upstream recovery path. Receipt-bound strict Steering does not resume/replay a missing session or fall back to redirect, interrupt or a subsequent turn. Removing the Neo contribution restores native keys and the explicit native Steer button.

With Neo active: idle Enter sends; busy Enter queues; Ctrl+Enter requests strict Steering; Tab accepts a suggestion into an editable, undoable draft; Esc dismisses the suggestion. Text and supported image attachments clear only after the matching delivery receipt. Existing image-reference limitations still apply; this is not native multimodal Steering.

## Installation Boundary

Build in an isolated checkout at the exact Desktop baseline. Bind the complete modified source set, lockfile/toolchain context and renderer output to a sealed build receipt. The locale-key manifest is a build-only input, not an additional installer write target.

Reuse the existing `host/installer/` check/apply/rollback entry points with a new private, machine-bound manifest. Refuse unknown source, plugin or packaged-runtime drift; preserve the Electron executable, ASAR, main and preloads. Do not reset prediction settings, provider/model/effort or candidate decisions. A successful check is not an installation, and an installation receipt does not prove the current window loaded the new renderer.

Any live switch still requires the task's maintenance authorization and safe affected-owner checkpoints. Backend restart is not required merely to prepare this Desktop-only candidate. Live gray text, Tab/Esc, queue keys, text/image Steering and rejection retention require separate acceptance after the correct window loads it.

Official updates remain official: an update can overwrite an unmerged host adaptation. Disable/uninstall the overlay before updating, then validate a newly compatible bundle. No upstream merge or automatic compatibility is implied.

## Validation Record

The isolated versioned SDK contract was red before the host seam was added. Targeted composer/Steering regressions, the full Desktop TypeScript check, locale-key check and code-health ratchet have passed during preparation. An additional regression proved that the native Steer button must retain its `steer` mode when the default Enter action is `interrupt`; the candidate was corrected and that regression passed.

The first full UI attempt ran 11,322 passing assertions but caught one unhandled jsdom/Radix asynchronous exception during `profile-rail-fleet.test.tsx`; its real exit code was **1**, so that attempt is **not a green suite**. Its cause is not attributed to the baseline without a controlled comparison.

On the frozen final candidate, the full UI-plus-Electron run initially recorded 14,909 passes, 3 failed assertions and 23 skips, plus three files blocked during Electron import. The six affected files were blocked by missing isolated Electron binaries or the bundled UV tool not being on PATH. After preparing those tools, all affected files were rerun unchanged. The portal fixture additionally needed its own access-control-free, TCP-disabled virtual X display because its deliberately narrow child environment does not forward Xauthority. The real source-launcher fixture ran in a verified private PID namespace, not alongside production agents, and exercised health and RPC with both clean and poisoned legacy-interpreter inputs.

The latest complete result for each exact file, combining that full run with the six targeted environment-repair retests, contains **14,944 passing assertions, 23 skips and no remaining failed assertions**. This is **not** relabelled as one atomic exit-0 full run. The earlier unhandled UI exception did not recur in the final full run. The plugin suites passed **76 Python tests** and **41 Node tests**; all **12 repository checks** passed. ESLint has **0 errors and 45 warnings**; these warnings are not represented as a clean lint report.

The final Windows renderer built with matching pre/post source seals. The existing installer passed live-target read-only preflight and an isolated Windows apply/repeat/foreign-edit-refusal/rollback/repeat rehearsal, preserving all six native runtime fingerprints. **No live installation, client reload, independent-review verdict or live gray-text/key/image acceptance is inferred from these results.**

## Audit Adjudication And Receipt Repair

An explicitly requested Opus 5.5 / Medium audit examined the frozen adaptation in four independent read-only module packets. All four original verdicts were `passed=false`; those verdicts are retained, not relabelled as model approval. The packet description incorrectly presented the round-wide inventory as if each packet held all 53 files. The union contains every changed source file, but each reviewer only saw its own packet. Integration and dependency questions were therefore adjudicated separately against the actual producers, consumers and tests.

The suspected plugin-removal Ctrl/Cmd+Enter regression was disproved with the real composer. Routed tile composers receive `ownerRoute.targetProfile || ownerRoute.profile`, matching the deletion lifecycle event; using the Desktop alias instead would be incorrect. The formal plugin context stamps registration provenance after spreading caller data. The image decoder's source bytes match the pinned backend and enforce byte/pixel/type limits and session ownership. The user-facing failure copy already says delivery is unconfirmed and warns users to check delivery before retrying.

A confirmed non-blocking receipt-feedback defect was repaired after that audit: a matching explicit image rejection now resolves the waiter as false immediately, preserving the draft and without resending. Successful-delivery matching and draft-clearing gates are unchanged. Three rejection regressions were red before the fix and green afterward; two plugin-removal key regressions and a routed-profile lifecycle regression were retained. This small post-audit repair is distinguished from the original reviewed snapshot; no new model passing verdict is claimed.

Fresh final validation covers **14,950 passing assertions and 23 skips across 1,694 Desktop test files**. The main UI/Electron invocation exited 0; the real source-launcher file was intentionally run separately in a private PID namespace and also exited 0. These are two explicit, non-overlapping invocations, not one atomic full-suite process. All 12 repository checks and the plugin's 41 Node / 76 Python tests passed. Initial plugin Python attempts used an incomplete host import/dependency entry; their failures are retained, and the successful rerun used the previously validated bundled-Python `hermes_bootstrap` entry without weakening assertions or changing Python product code.

Support is limited to the exact split-host pair above, verified by the machine-bound installer and backend fingerprints. A frontend SDK capability number is not a general capability negotiation protocol for arbitrary other gateways. Connecting an unverified backend is outside this adaptation's supported scope; revalidate before doing so. Installation, window activation and physical keyboard acceptance remain separate from this source/test record.
