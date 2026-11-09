# Neo Composer 0.4.2 / Hermes v0.22.2

Target source: `d923a5eb487a17c0a68801bba9ef0f56c81040a8`.
The official renderer still needs the separately built composer behavior v2 seam. Installing this plugin alone does not patch or rebuild core.

## Verified for this adaptation

- Backend: 58 tests passed, including independent prediction route and fail-closed endpoint/credential constraints.
- Windows native composer/session regression: 886 tests in 89 files passed. Full Desktop TypeScript check passed.
- Plugin controller/registration plus compatibility/predecessor validation: 14 tests passed.
- Read-only ESLint: no errors; four pre-existing React hook dependency warnings remain.
- Windows Vite renderer built, with exact source pins sealed before/after compilation and a complete renderer hash inventory.
- Windows Chromium fixture: ghost persistence beyond 30 seconds, refresh reuse, durable Esc dismissal, editable Tab acceptance/undo, idle Enter send, busy Enter queue, Shift+Enter newline and Ctrl+Enter through native prompt actions to the real `session.steer` handler and safe-boundary delivery all passed. No `session.redirect` or interrupt was triggered. Inference and tool execution in this fixture are deterministic substitutes.
- Isolated Windows filesystem rehearsal: exact pinned predecessor upgrade, repeat apply, runtime drift/foreign-edit rejection, rollback/repeat rollback passed; executable/ASAR/main/preload stayed unchanged.
- A separate real subscription-backed `openai-codex` / `gpt-6-luna` low-effort request on synthetic input produced a valid 77-character candidate in 6.819 seconds; main configuration was unchanged. This is not live-conversation gray-text evidence.
- One independent review round, one AGY Gemini reviewer, two bounded module packets. Both raw verdicts passed; the wrapper required primary adjudication because suggestions were present. Two native-code suggestions were adjudicated non-blocking P3; the operational pause/restart reminder remains a live-activation requirement.

## Not established by these results

These are not screenshots or key tests from a user's currently running packaged Desktop window. Candidate installation, safe task-pause confirmation, controlled backend/client restarts and live-window acceptance are separate stages. This document does not claim they happened.

Prediction settings, the main chat provider/model/effort, credentials and existing candidate decisions must not be reset during upgrade. Unknown source/runtime/plugin drift must stop installation. Keep the prior package and renderer controls for hash-bound rollback.
