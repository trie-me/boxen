# Backup, offline restore and disconnected transfer

For the current container configuration use `--env-file deploy/.env` and retain
the same selected AI overlays on commands below. The image-only base manifest
has no build instructions; source builds additionally use `compose.build.yaml`.
The separate `/models` volume and CA state must be preserved independently of
inventory backups. See [container storage](container-storage.md).

All examples run from the repository root, with the same configuration as the services. Replace the explicitly marked backup/installation values with the selected generation's real values.

## Daily worker backups

Keep `boxen worker` running. After an active owner exists it requests a backup when there are no creating/verifying backups and the newest backup attempt is over 24 hours old (or none exists). It checks on startup and subsequent ticks. **This is not a 02:00 local-time scheduler**: failed attempts also count toward the next 24-hour interval. Check the owner System/Backups view and manually retry failures after addressing the cause. There is no configurable clock-time scheduler or automatic retention pruning yet.

Backups are stored at `$BOXEN_DATA_DIR/backups/backup-<id>`. They contain a SQLite online snapshot, referenced ready-image originals, public settings, a manifest and checksums. Creation verifies DB integrity, foreign keys, referenced originals and checksums. Derivatives, session secrets, model weights and Caddy CA state are not included. The backup resides on the same disk by default; copy verified generations to protected separate storage for disk-loss protection. Backups are not encrypted by this application.

For new uploads, “originals” means the stored, normalized WebP (maximum 2,048-pixel edge), not the file before upload. Older photos keep their existing format and bytes. Both are included in backups. Derivative repair rebuilds previews from these stored files without modifying them; it does not recompress existing originals or recover discarded upload resolution/metadata.

The current schema is **0003** (authentication store, following tags and collections). Known
0001, 0002 and 0003 backup histories are accepted only with their exact pinned migration
checksums and matching Alembic head (or the supported pre-Alembic 0001 history).
Verification never rewrites an old backup. Restore upgrades the verified staging
database before activation, leaving the original manifest and snapshot intact.
Unrecognized, gapped or altered migration histories are rejected.

Passwords now depend on the installation's private password pepper, normally
`$BOXEN_DATA_DIR/secrets/password.pepper` (or `BOXEN_PASSWORD_PEPPER_FILE`).
Normal inventory backups deliberately exclude that pepper, session keys and OAuth
client secrets. Keep a separately protected copy of these secrets, the provider
configuration and TLS state for host-loss recovery. Restore checks the pepper's
fingerprint before activation; a missing or different pepper must be recovered,
not regenerated. Never put the pepper beside a publicly accessible database backup.
Restore revokes sessions and discards pending OIDC callbacks. See
[authentication and administrator recovery](/help/administration).

For a forward upgrade, take and verify a backup before replacing the running
release. Stop web and worker, retain the same configuration/data directory, run
`boxen init`, and verify the new release before resuming use. Initialization
requires an exclusive runtime lock and will refuse to migrate while services
hold it. A failed transactional migration leaves the previous schema intact;
do not force startup or edit migration checksums to bypass an error.

The owner UI queues a backup for the worker. For a deterministic CLI backup, stop the worker first so it does not compete for the same operation (web may remain running):

```sh
# Native, after stopping the worker:
.venv/bin/boxen backup

# Compose:
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml stop worker
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps web backup
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml up -d --no-build --pull never worker
```

Confirm the returned JSON says `"status": "verified"`; the command's exit code alone is not a backup-success check. To export a selected Compose generation:

```sh
mkdir -p .local/boxen-backup-export
BACKUP_ID='replace-with-returned-backup-id'
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml cp "web:/var/lib/boxen/data/backups/backup-$BACKUP_ID" .local/boxen-backup-export/
```

Read that generation's `manifest.json` for its `installation_id`; keep the manifest/checksum files with every copy. Compare an independently retained manifest digest when authenticity matters: checksums detect corruption but do not authenticate an attacker-replaced manifest. Protect separate copies of the complete installation and TLS state for host-loss recovery.

## Offline restore with quarantine

Restore requires an initialized, compatible target with the **same installation ID** as the backup, its existing secrets and a writable parent directory. A new `init` on another host generates a different identity and is not a cross-installation import. Preserve/relocate the existing installation first for host migration. There is no supported bare-backup-to-new-installation import command.

Stop web, worker and any separately managed inference runtime; allow shutdown to finish. Never remove SQLite WAL/SHM files to force a restore. Verify enough disk space for another database/media copy. Preflight checks the manifest/backup and installation identity; it is not the full disk/ownership/host compatibility preflight described in the design. Apply obtains an exclusive runtime lock and checks disk reserve. Keep other CLI operations stopped during the swap.

Native commands (data directory must be a child directory, not a filesystem mount point):

```sh
BACKUP_PATH='/absolute/path/to/backup-ID'
INSTALLATION_ID='replace-with-matching-installation-id'
.venv/bin/boxen restore preflight "$BACKUP_PATH" --confirm-installation "$INSTALLATION_ID"
.venv/bin/boxen restore apply "$BACKUP_PATH" --confirm-installation "$INSTALLATION_ID"
.venv/bin/boxen repair-derivatives
.venv/bin/boxen restore verify
```

Both `preflight` and `apply` require `--confirm-installation`; `verify` accepts neither a backup path nor a confirmation requirement. For a generation still in the Compose volume:

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml stop caddy web worker
BACKUP_ID='replace-with-selected-backup-id'
INSTALLATION_ID='replace-with-matching-installation-id'
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps web restore preflight "/var/lib/boxen/data/backups/backup-$BACKUP_ID" --confirm-installation "$INSTALLATION_ID"
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps web restore apply "/var/lib/boxen/data/backups/backup-$BACKUP_ID" --confirm-installation "$INSTALLATION_ID"
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps web repair-derivatives
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps web restore verify
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml up -d --no-build --pull never web worker caddy
```

For external backup media, add `--volume /absolute/backup-parent:/restore-input:ro` to each `compose run` before `web` and use `/restore-input/backup-ID` as the backup path. No dependency services are started by these restore commands.

Apply retains the former root as `data.quarantine-<id>` beside `data` and reports its exact path. It preserves existing secrets, hard-links existing model and backup history, restores originals, revokes sessions and cancels interrupted jobs. Derivatives must be rebuilt before resuming. Verify integrity, log in again and check representative inventory, photos, search and labels. Do not restart after an unsuccessful verification. Search mismatches require the owner search-rebuild maintenance action and re-verification.

Keep quarantine until acceptance. It is not a second independent backup because models/history can share hard links. No quarantine-cleanup CLI is provided. Deletion is a separate, explicitly scoped owner action after confirming the precise path and an independent verified backup; no automatic deletion command is included here.

## Transfer without network access

The image-save example uses the default local tags. Substitute your configured
release references and include the optional AI image when needed. The deployment
archive below includes `deploy/.env` if present; inspect it for sensitive paths
and protect it. Never put credential values or private CA material there.
Copy the selected model profile separately; it is not inside the app image.

On a connected build machine of the target architecture, build both images and package the deployment instructions. These are operator-created transfer files, not a signed/qualified release bundle:

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.build.yaml build web caddy
mkdir -p .local/boxen-transfer
docker image save --output .local/boxen-transfer/boxen-images.tar boxen:0.1.0 boxen-caddy:0.1.0
tar -czf .local/boxen-transfer/boxen-deployment.tar.gz README.md deploy docs/operations docs/verification/deployment.md
(cd .local/boxen-transfer && sha256sum boxen-images.tar boxen-deployment.tar.gz > SHA256SUMS)
```

Copy these three files on removable media. Obtain the expected checksum list through a trusted independent channel. On the disconnected target, with Docker/Compose already installed:

```sh
# In the transferred bundle directory:
sha256sum --check SHA256SUMS
docker image load --input boxen-images.tar
mkdir boxen-release
tar -xzf boxen-deployment.tar.gz -C boxen-release
cd boxen-release
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps --pull never init
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml up -d --no-build --pull never web worker caddy
```

This initializes a **new** installation. For relocation, stop the old installation and securely transfer its complete application volume, `caddy-data` and `caddy-config` instead, preserving UID/GID 10001 and modes; restore those volumes before starting. Include deployment configuration and any separately provisioned model/runtime dependencies. Treat this archive as containing credentials and private CA keys. A same-installation host relocation and full disk-loss recovery have not been rehearsed here; do not discard the original host/volumes based solely on these instructions.

Runtime images embed Python dependencies, frontend assets, fonts and schema artifacts. The transfer path runs no package installer or image build on the disconnected host. Native offline installation additionally needs matching Python/Node/uv/pnpm executables and a complete wheel/package cache; no preassembled native offline bundle is supplied. No model is automatically downloaded or bundled.
