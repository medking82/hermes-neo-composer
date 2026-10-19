# Upgrade Resilience And Local Setup

## Two Independent Layers

**SDK compatibility mode** uses the official draft and owner APIs. The status-bar **Neo Composer · Suggestions** button previews a candidate and offers explicit **Insert As Draft**, **Dismiss** and **Refresh**. It does not create native inline gray text, intercept Tab/Esc or submit a message. A missing behavior/strict marker does not remove prediction settings or the local enhancement controls. Missing owner/draft APIs, an unowned chat, a busy chat or an incompatible prediction backend fail closed with a notice.

**Native enhancement** supplies the host-owned inline rendering and key arbitration. Behavior v2 without strict receipts retains suggestions but registers no Neo busy-key override. A renderer's strict-adapter marker identifies its frontend interface, not support on every connected gateway. Strict delivery still needs the verified backend contract; rejection never falls back to interrupt, redirect or replay.

The candidate adapts Desktop `3752497cc4d214023f4736559a5f0e58621af9ff` and retains the existing strict backend at `d923a5eb487a17c0a68801bba9ef0f56c81040a8`. It does not install/restart the backend or change models, inference settings, credentials, the Electron shell or the official update channel. The older 9e01b44 adaptation is a separate historical package.

## Plugin Settings Entry

1. Extract a trusted, prepared native package to a persistent local Windows directory. Keep all its files together; Node must be available on PATH.
2. Open **Settings → Plugins → Neo Composer → Native Enhancement**.
3. Choose its **NeoComposerSetup.cmd** with **Select Local Installer**. Selection only saves a path; it does not run it.
4. Use **Check Installation**, **Install / Repair** or **Uninstall Enhancement** explicitly. These open the corresponding fixed sibling launcher. They do not send a command to the remote gateway.
5. Read the local console/receipt result. The plugin only reports **Open Request Sent**; OS acceptance of an open request is not proof of installation.
6. Save any unsent draft before manually reloading the window. Setup never reloads a window or restarts a service. Installed files, loaded plugin/adapter and live interaction are separate acceptance stages.

The path picker rejects remote URLs, UNC paths, arguments and unexpected launcher names. **A file-name check does not authenticate its publisher.** Choose only a trusted package; an executable selected from an untrusted directory is not made trustworthy by this UI. No generic shell endpoint, privileged installer daemon or timer is introduced.

These controls mount independently of prediction-settings loading, so a prediction backend outage does not hide the repair entry.

## Native Package Boundary

`host/installer/setup.mjs` selects an exact full source HEAD from a local catalog, checks the cataloged tool and package hashes, and uses the existing `prepare.mjs` / `install.mjs` transaction. Unknown or ambiguous versions refuse before patching. Existing installations are checked again, including every owned renderer hash; source equality alone is not enough. Failed preparation/apply is reported, with rollback restricted to that transaction's own receipt and known preimages. Unknown edits or a newer source HEAD are not overwritten with an old backup.

Independent enhancement manifests declare:

```json
{"pluginPolicy":"preserve","pluginFiles":[]}
```

Install and uninstall therefore leave the independently installed SDK plugin alone. A preserve policy with plugin writes, or an unknown policy, is rejected. Legacy manifests retain their original transactional plugin-file behavior; their old receipts are not relabeled as independent packages.

For a maintainer with a sealed renderer and a verified release seed, prepare and assemble in a fresh output directory:

```text
node host/installer/prepare.mjs <desktop-root> <prepared-bundle>
node host/installer/package-setup.mjs <new-output-directory> <desktop-root> desktop-3752497 <prepared-bundle>
```

The assembler inherits and checks the sealed build receipt rather than approving a changed receipt by recalculating it. It copies only the declared payload, not unrelated files or prior transaction backups/receipts. It is a packaging tool, not a runtime compiler or an automatic downloader.

A catalog can contain multiple explicitly validated versions. It cannot adapt an arbitrary future Hermes release. When no matching package exists, leave SDK mode installed and obtain a separately validated package; do not pin/downgrade Hermes or force an old backup onto it. Official updates can overwrite an unmerged native enhancement.

## Minimal Upstream Boundary

The native proposal remains separate from the prediction plugin and its installer: [existing PR #139051](https://github.com/NousResearch/hermes-agent/pull/139051). Its acceptance is not assumed.

The host boundary is generic: owner-qualified composer environment/lifecycle, a controller with `update`, `ghost`, `decide`, `accept` and `dispose`, and host-owned rendering/undoable editing/key execution. The plugin owns inference, persistence and policy. Strict Steering is a separate, receipt-bound backend capability, not a prerequisite for registering suggestions. SDK preview/insertion remains the compatibility path when the native seam is absent. No proposal here grants a plugin global DOM/key interception or moves installation into an arbitrary gateway REST handler.

## Candidate Acceptance

This document describes the 0.5.0-rc.1 candidate, not a claim that it is published, installed or loaded. Unit/integration results, Windows filesystem/launcher rehearsals, isolated SDK rendering and live Desktop interaction must be reported separately. Synthetic gateways and draft adapters are not real model output or real-window acceptance.
