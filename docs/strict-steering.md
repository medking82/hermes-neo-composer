# Strict Steering and future image support

## 0.4.4 contract

Busy Enter queues the next turn. Busy Ctrl+Enter requests only `session.steer` with `strict: true` and a correlation ID. Unsupported hosts, compression, attachments and ended turns fail closed; they never trigger redirect, interrupt, resume-and-submit or next-turn queueing.

An RPC acknowledgement means buffered, not delivered. Neo keeps the submitted draft until the matching safe-boundary receipt. Success means a new out-of-band user row was appended after a tool boundary; it does not prove that the model has read or acted on it. New typing and attachments are never cleared by an older receipt. Disconnects and uncertain delivery retain the draft without automatic retries.

The agent preserves legacy Steering behavior separately. Strict items are rejected at turn end and fenced against late arrivals. Starting another turn rejects any strict leftovers from an exceptional exit before reopening the strict buffer.

The standalone plugin owns keyboard policy. A separately installed, versioned host seam supplies native composer integration and delivery receipts. The plugin does not modify core files. An official host upgrade can overwrite an unmerged host patch; unknown compatibility fails closed.

## Images: design consultation, not shipped functionality

A Gemini 4 Argon Medium design consultation favored a phased plugin-first approach. Its recommendations are design input, not code validation.

1. Reuse session-scoped, staging-only file upload. Do not use an upload route that adds images to the next normal prompt's shared `attached_images` state.
2. Add narrow native attachment transaction access for the active composer, retaining thumbnails and text until confirmed injection. Validate actual image type, size, canonical ownership and path confinement before accepting references. Keep image bytes, paths and references out of ghost-text prediction requests.
3. Initially send a strict text reference requesting the existing vision tool. Label this **reference injected / image inspection unconfirmed**. The tool must already be available in the session; no mid-turn toolset changes. Injection cannot guarantee a tool call or image comprehension.
4. If native multimodal Steering is required later, reuse the same staged references but resolve them into provider-compatible image content at a safe boundary, with capability checks and history support. That requires backend/core work and is not a pure UI-plugin feature.

This release does not stage or steer images. The consultation's initial suggestion to clear attachments on an RPC acknowledgement is **not** adopted: the stricter delivery receipt is required instead. A side-effect-free upload and an end-to-end reference/tool test must succeed before image support can be claimed.
