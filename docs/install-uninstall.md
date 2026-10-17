# Neo Composer — install, uninstall and official updates

Neo Composer 0.4.5-rc.1 keeps prediction, preferences and composer policy in the plugin. The separate host patch supplies the native composer seam, strict Steering delivery receipts and session-owned image staging that the v0.22.2 plugin API lacks. This image candidate is not a production activation; a shared-runtime switch needs separate authorization. Internal ID `neo-next-prompt` is retained so existing settings and decisions are not migrated.

## Supported boundary

- Hermes v0.22.2, exact source commit `d923a5eb487a17c0a68801bba9ef0f56c81040a8`.
- A backend source bundle and a separately fingerprinted Windows Desktop bundle. A Windows bundle is specific to its frozen predecessor; it is not a universal installer for arbitrary modified installations.
- Node 24 or newer and Git. Install the unified plugin through the existing Hermes plugin mechanism; its host patch is a separate, explicit operation.
- No replacement of `Hermes.exe`, `app.asar`, the install stamp, Electron main or either preload. No new updater, background daemon, credentials, automatic restart or force mode.

**Before applying or uninstalling:** obtain safe-pause confirmation from every affected execution owner, then stop the owning backend/client through their existing lifecycle. Merely notifying an owner is not confirmation. These commands change files; they do not stop services or make an already imported Python module live.

## Backend host patch

Unpack the backend bundle into a durable directory and retain that whole directory for uninstall. Replace `ROOT` with the backend's Hermes source checkout and `BUNDLE` with the unpacked bundle directory. Invoke the installer from that directory:

```sh
node install.mjs check-backend ROOT BUNDLE
node install.mjs apply-backend ROOT BUNDLE
node install.mjs check-backend-update ROOT BUNDLE
```

The installer checks the supported commit, frozen preimages, all ten source payloads and the coupled interface fingerprints. It backs up only its declared files and verifies the installed bytes. Unrelated files are not overwritten. Existing settings, sessions and prediction decisions are outside its write set.

Uninstall the backend host patch with:

```sh
node install.mjs rollback-backend ROOT BUNDLE
```

Uninstall validates all backups before restoration, removes newly added source files and restores exact preimages. Unknown later edits or a changed source commit stop it rather than overwriting them. Retain `backend-backup/` and `backend-receipt.json`; do not copy a receipt between targets or edit a frozen release manifest after applying it.

Interrupted operations are not blindly resumed by `apply`. A `prepared` receipt is saved before any target write, and rollback accepts the known before/after mixture. If backup preparation failed before a receipt was created, no target source was changed: preserve that failed bundle and use a fresh copy only after `check-backend` confirms the exact predecessor. A hard process kill or power loss can leave an operation lock or scratch file; automatic stale-lock removal is intentionally absent. Confirm the previous process has exited and inspect receipt, backup and file ownership before manual recovery. Do not delete unknown files or launch a second installer while the first may still be active.

## Windows Desktop host patch

The Desktop bundle contains the already sealed renderer, its source/provenance inventory, the plugin's Desktop half and the fixed-release installer. It does not rebuild or replace the Electron shell. The bundle's `release-seed.json` must already describe the independently verified predecessor; preparation must never adopt arbitrary current hashes as approval.

From the Desktop bundle directory, with `ROOT` pointing to the PC's Hermes source checkout:

```sh
node prepare.mjs ROOT BUNDLE
node install.mjs check ROOT BUNDLE
node install.mjs apply ROOT BUNDLE
node install.mjs check-update ROOT BUNDLE
```

Preparation is create-only. If `release.json` already exists, use `check`, not preparation again. A dirty packaged shell without independently approved native fingerprints is refused. Do not turn a copied test-target fixture into live approval.

Uninstall the Desktop host patch with:

```sh
node install.mjs rollback ROOT BUNDLE
```

This restores the previous source, renderer entry files and Desktop plugin files. It removes only renderer assets recorded as introduced by this release, and refuses to remove an introduced asset whose content has since changed. Pre-existing assets and all protected native files are preserved. Retain `backup/`, `receipt.json` and `release.json` for rollback ownership. Uninstalling this patch restores the prior state; it does not promise that prior state was an unmodified official installation.

## Normal official upgrades

The supported route is **uninstall this host patch on both machines first, then use the official updater**. This release does not intercept the update button or automatically reapply a patch.

1. Disable prediction, coordinate a safe stop, and run the two rollback commands above. Keep their receipts and backups. If a guard refuses because another owner edited a file, resolve that exact edit; do not reset the whole checkout.
2. Use the official update channel and updater. For source CLI installs, `hermes update --keep-stash` leaves any remaining local edits safely parked rather than silently restoring them onto the new version. Do not force-apply an old stash or this patch afterward.
3. Check the actual new backend and Desktop versions independently. Reinstall only an explicitly compatible bundle. An unknown version is refused; the plugin must not substitute redirect/interrupt for unavailable strict Steering.
4. An old uninstaller is not a downgrade tool. After a version change, it refuses to restore old backups over the newer installation.

The plugin package can remain installed while its dependent host capability is unavailable, but the strict contribution is disabled with a notice. An uninstalled/disabled enhancement supplies no strict-Steering guarantee; do not mistake the official client's original shortcut behavior for Neo Composer's path.

## Verification limits

File-operation acceptance and real runtime activation are separate. The backend installer was exercised against an isolated checkout of the exact official source. The Desktop installer was exercised against a copied Windows installation, including idempotence, foreign-edit refusal, native-file preservation and removal of introduced renderer assets. Synthetic version-change tests verify refusal, not an actual future-version upgrade.

The latest official release checked during this delivery is v0.22.2. An official update availability check is not a cross-version upgrade rehearsal. No claim is made that an old patch will work unchanged on future Hermes releases. Live backend restart, packaged-window registration and real Steering acceptance require the separately coordinated activation receipt.
