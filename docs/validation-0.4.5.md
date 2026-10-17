# Neo Composer 0.4.5 — Validation and Limits

## Release and Installed Identity

The live acceptance used installed **0.4.5-rc.1**, source `7e651e7c299119c38fbf94671e414f05435f2852`, on Hermes v0.22.2 (`d923a5eb487a17c0a68801bba9ef0f56c81040a8`). Formal **0.4.5** changes only version metadata, generated plugin version/hash and documentation. The host patch, behavioral source, renderer output, installer implementation and compatibility pins are unchanged. The package is not a new native Windows application build or a universal installer for arbitrary modified hosts.

The installed RC identity, applied manifests and rollback receipts remain intact. Publication did not reinstall, restart or relabel that installation. Its accepted behavioral bytes are reused; the final version metadata receives separate deterministic build, registration and package-integrity validation. The earlier independent review covers the unchanged implementation, not the later release metadata/documentation.

## Real Packaged-Window Acceptance

A bounded synthetic fixture was entered through the original conversation's native Windows composer, not through a substitute browser or direct dispatch call:

- Busy **Ctrl+Enter** staged an image and delivered a strict Steering message at a safe tool boundary. The actual request and delivery receipt matched the exact Steering ID and ordered image-reference batch.
- The original agent called its existing **`vision_analyze`** on the delivered image. The recorded result's pixels matched the staged original; the observed text and left-to-right colored shapes matched the synthetic fixture. A path in a prompt alone was not accepted as evidence of reading.
- The unchanged submitted text and thumbnail cleared together after the matching receipt. Normal next-turn queue state was unchanged by Steering.
- A separate **slash-command plus image** Ctrl+Enter attempt was explicitly rejected before dispatch. The text and thumbnail remained, with no backend delivery or next-turn fallback. Only this owned synthetic rejected draft was subsequently removed.
- A single **ordinary Enter**, text-only input was queued while busy, then delivered after the prior response completed as a separate ordinary user turn. Its persisted body matched the queued text exactly; the gateway recorded **`kind=user`, `images=0`**. It inherited neither the preceding Steering image references nor the rejected draft.
- Temporary diagnostic wrappers were restored and removed, and DevTools was closed. The current attempts' clipboard text and observed text-format set were restored. Exact restoration of every clipboard format from an earlier failed attempt is not established.

An earlier image attempt failed and retained its draft. Its exact historical failure branch was not captured and remains unproven; later success on the same installed implementation is not claimed as a product fix or proof of that failure's cause. The failed attempt and restoration limits remain in private evidence.

**Capability boundary:** the receipt still means **reference injected / image inspection unconfirmed**. The later actual vision-tool call is separate evidence. **Native multimodal Steering is not implemented**, and this observed inspection is not a guarantee that every future injected reference will be inspected automatically. Main model/provider/effort and the existing toolset were not changed.

## Reused Frozen Checks — Not All Green

These completed checks belong to the unchanged candidate implementation; they were not rerun to promote its version label:

- Plugin Python: **76 passed**. Installer/controller/registration Node checks: **39 passed**; forced async registration: **6 passed**.
- Focused Desktop image/Steering checks: **52 passed**. Full Desktop UI: **10,924 passed, 2 failed, exit 1**.
- Both UI failures are in `src/store/voice-prefs.test.ts`: `keeps the desktop toggle local across config refreshes` and `migrates the legacy preference once, not on every refresh`. The fixed clean base, identical locks and same runtime reproduce both with actual `'false'`, expected `null`; candidate and baseline focused runs each have 16 passed / 2 failed.
- Full package TypeScript, the Electron i18n-key contract and repository checks passed. The renderer-only build contains **1,063 files** with unchanged source pins; no executable/ASAR/main/preload replacement is included.
- The backend installer's official-source and 0.4.4-text-seam predecessor paths passed check, apply, idempotent apply, compatibility readback and exact rollback on disposable targets. Windows file-operation rehearsals remain separate from the later live acceptance.

### Complete Python Comparison

Both full runs returned **exit 1**, with identical lockfiles/runtime/runner options and separate PID/configuration containment:

| Snapshot | Passed | Failed | Setup Errors | Skipped | Files |
|---|---:|---:|---:|---:|---:|
| Candidate | 60,470 | 87 | 250 | 878 | 5,569 |
| Fixed clean base | 60,433 | 89 | 250 | 878 | 5,565 |

All 87 candidate failures were paired with the complete fixed-base run: 67 have matching assertion/exception values after normalizing only ephemeral paths/addresses/stat metadata; 19 share the dependency-DNS failure and assertion; one shared fixture wheel-build failure cannot fetch `setuptools>=75.3.4`. All 250 setup errors are shared dependency/DNS failures in the network-disabled environment: 238 PM/uv setup failures and 12 urllib/socket failures. **Those test bodies remain unexercised, not passed.** The five changed Python test files passed in that full run.

No candidate-only failed/error test IDs or unmatched failure conditions were found. The two baseline-only failures (`test_batched_completions_follow_the_owning_profile[batch_child_first-handoff-False]` and `test_our_own_pid_is_ours_only_at_our_exact_creation_time`) are retained, not claimed as fixes. This is a matched-failure attribution, not an all-green or unrestricted-host result.

## Independent Review and Remaining Scope

One Gemini 4 Argon Medium review round covered two complementary packets from the same frozen implementation. Both original model verdicts passed; the wrapper returned `needs_adjudication` (exit 2). Three unlabelled suggestions were independently classified as non-blocking P3: defensive session-check consistency, redundant synchronous draft reads and a maintenance-fixture directory-preparation suggestion. They remain deferred; no extra review was opened for formal version metadata.

Fresh whole-suite execution, additional model review, native multimodal delivery, automatic tool-selection guarantees, real power-loss recovery and a future Hermes cross-version upgrade were not tested in this closeout. Unchanged evidence was reused; new metadata validation is not represented as a new behavioral review. Private conversations, UI traces, credentials, machine-specific installation manifests and raw logs are not part of the public package.

Official updates can overwrite unmerged host changes. Follow [the explicit uninstall and compatibility procedure](install-uninstall.md); publication is not permission to install/restart another target, adopt unknown native fingerprints or bypass drift checks.
