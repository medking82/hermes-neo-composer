# Strict Steering and staged image references

## 0.4.4 contract

Busy Enter queues the next turn. Busy Ctrl+Enter requests only `session.steer` with `strict: true` and a correlation ID. Unsupported hosts, compression, attachments and ended turns fail closed; they never trigger redirect, interrupt, resume-and-submit or next-turn queueing.

An RPC acknowledgement means buffered, not delivered. Neo keeps the submitted draft until the matching safe-boundary receipt. Success means a new out-of-band user row was appended after a tool boundary; it does not prove that the model has read or acted on it. New typing and attachments are never cleared by an older receipt. Disconnects and uncertain delivery retain the draft without automatic retries.

The agent preserves legacy Steering behavior separately. Strict items are rejected at turn end and fenced against late arrivals. Starting another turn rejects any strict leftovers from an exceptional exit before reopening the strict buffer.

The standalone plugin owns keyboard policy. A separately installed, versioned host seam supplies native composer integration and delivery receipts. The plugin does not modify core files. An official host upgrade can overwrite an unmerged host patch; unknown compatibility fails closed.

## Historical image design (0.4.4; no image implementation)

A Gemini 4 Argon Medium design consultation favored a phased plugin-first approach. Its recommendations are design input, not code validation.

1. Reuse session-scoped, staging-only file upload. Do not use an upload route that adds images to the next normal prompt's shared `attached_images` state.
2. Add narrow native attachment transaction access for the active composer, retaining thumbnails and text until confirmed injection. Validate actual image type, size, canonical ownership and path confinement before accepting references. Keep image bytes, paths and references out of ghost-text prediction requests.
3. Initially send a strict text reference requesting the existing vision tool. Label this **reference injected / image inspection unconfirmed**. The tool must already be available in the session; no mid-turn toolset changes. Injection cannot guarantee a tool call or image comprehension.
4. If native multimodal Steering is required later, reuse the same staged references but resolve them into provider-compatible image content at a safe boundary, with capability checks and history support. That requires backend/core work and is not a pure UI-plugin feature.

Version 0.4.4 did not stage or steer images. The consultation's initial suggestion to clear attachments on an RPC acknowledgement was **not** adopted: the stricter delivery receipt is required instead.

## 0.4.5-rc.1 candidate: reference + existing vision tool

`session.steer_image_stage` sends original bytes, never a client path or thumbnail, to a running session that already has `vision_analyze`. It does not modify normal `attached_images`. The server verifies PNG/JPEG/WEBP contents, a 10 MiB decoded-size limit and a 20-million-pixel limit. It returns an opaque session-owned reference, not a server path. Each request accepts one to four distinct references; each session can retain eight pending stages, with a 15-minute expiry checked during stage/claim operations. File digest, size, canonical parent, symlink and hardlink checks are repeated before claim. Failed/abandoned staging can consume pending slots until expiry; the client never silently retries. Delivered originals remain available to the existing vision tool. This is not a general image-retention or secure-erasure service.

A strict request claims the complete batch only after validation. Receipt acceptance requires the same Steering ID, `image_delivery=reference_injected` and the exact ordered reference batch. The composer clears text and thumbnails only if both still equal the submitted snapshot. Staging, turn-end, compression, disconnect and delivery failures retain the draft; none queue, interrupt or redirect. Prediction filters image/payload/reference and private-path lines before history excerpts.

The three evidence levels remain separate:

1. **Reference injected:** the safe-boundary delivery receipt; this is the UI success state.
2. **Image actually read:** the reused isolated Composer E2E calls the existing vision handler on the staged original, compares returned pixel bytes with the source digest, and retains those pixels. The main agent separately used its existing `vision_analyze` tool and correctly read the synthetic text and colored shapes. This verifies pixel delivery and actual visual inspection, not automatic model tool selection or a production client run.
3. **Native multimodal Steering:** not implemented. The Steering message remains text; image content is obtained only through the existing vision tool. No toolset, main model, provider or effort changes occur.

The candidate requires separate production activation authorization. Passing isolated tests or publishing this source does not authorize installation or a shared backend/frontend restart.
