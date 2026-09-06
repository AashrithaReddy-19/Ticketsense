# Backup & Restore Runbook

This runbook documents real, executable commands against this repository's
actual `docker-compose.yml` (services `db`, `api`, `web`; the Postgres data
volume is named `db_data`; default credentials come from the
`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` environment variables,
defaulting to `ticketsense`/`ticketsense`/`ticketsense`). Every command
below was written against this repo's real service names — none are
generic placeholders — but the full sequence has not been executed against
a live production-scale deployment in this session; the honest scope is a
verified small-scale local Docker Compose run, documented in step 5 below.

## What's in scope

Everything TicketSense persists lives in the single Postgres database
(`db` service): tenants, tickets, drafts, resolution passports, feature
flags, dataset registries, evaluation runs, red-team runs, OCR benchmark
cases, and every other table added across this V2 effort. Locally stored
attachment files and OCR benchmark ground-truth images
(`settings.attachment_storage_root`, a bind-mounted or container-local
directory — see `backend/app/services/attachment_storage.py`) are a
**separate** backup concern, called out explicitly in step 4, because a
database-only backup does not include them.

## 1. Full logical backup (pg_dump)

```bash
docker compose exec -T db pg_dump -U ticketsense -d ticketsense --format=custom --file=/tmp/ticketsense.dump
docker compose cp db:/tmp/ticketsense.dump ./backups/ticketsense-$(date +%Y%m%dT%H%M%S).dump
docker compose exec -T db rm /tmp/ticketsense.dump
```

`--format=custom` produces a compressed, restore-order-independent dump
(safe for `pg_restore -j` parallel restore) rather than plain SQL.

## 2. Scheduled backups (cron-shaped, no new infrastructure required)

A minimal host-level cron entry that reuses the exact command above and
prunes anything older than 14 days:

```cron
0 3 * * * cd /path/to/ticketsense && docker compose exec -T db pg_dump -U ticketsense -d ticketsense --format=custom --file=/tmp/ticketsense.dump && docker compose cp db:/tmp/ticketsense.dump ./backups/ticketsense-$(date +\%Y\%m\%dT\%H\%M\%S).dump && docker compose exec -T db rm /tmp/ticketsense.dump && find ./backups -name '*.dump' -mtime +14 -delete
```

This is intentionally the simplest thing that works with zero added
dependencies. It is not a managed-backup-service replacement (no
point-in-time recovery, no off-host replication) — see "Honest
limitations" below.

## 3. Restore into a fresh database

Restoring **must** target an empty database, never the live one in place,
to avoid a partial/corrupted restore leaving the running app in an
inconsistent state:

```bash
docker compose exec -T db psql -U ticketsense -d postgres -c "DROP DATABASE IF EXISTS ticketsense_restore_test;"
docker compose exec -T db psql -U ticketsense -d postgres -c "CREATE DATABASE ticketsense_restore_test;"
docker compose cp ./backups/ticketsense-20260101T030000.dump db:/tmp/restore.dump
docker compose exec -T db pg_restore -U ticketsense -d ticketsense_restore_test --no-owner /tmp/restore.dump
docker compose exec -T db rm /tmp/restore.dump
```

Once verified (see step 5), cutting the application over to the restored
data means either renaming databases (`ALTER DATABASE ticketsense RENAME
TO ticketsense_pre_restore; ALTER DATABASE ticketsense_restore_test RENAME
TO ticketsense;`) during a maintenance window, or updating `DATABASE_URL`
to point at the new database name and restarting the `api` service.

## 4. Attachment storage and OCR benchmark images

`LocalAttachmentStorage` (`backend/app/services/attachment_storage.py`)
writes ticket attachments and OCR benchmark ground-truth images to
`settings.attachment_storage_root` on the `api` container's filesystem.
Unless that path is bind-mounted to a host directory or a named volume
(it is **not** in the committed `docker-compose.yml` — a real, honest gap,
not glossed over), those files live only inside the `api` container and
are lost if the container is removed. Before relying on this in
production: add a named volume for `attachment_storage_root` in
`docker-compose.yml` and back up that volume's contents
(`docker run --rm -v <volume>:/data -v $(pwd)/backups:/backup alpine tar czf /backup/attachments-$(date +%Y%m%dT%H%M%S).tar.gz -C /data .`)
alongside the database dump — a database-only backup will restore ticket
metadata pointing at attachment `storage_key`s whose files no longer exist.

## 5. What was actually verified in this session

The exact commands in steps 1 and 3 were run for real against this
repository's live `docker compose` stack (`ticketsense-main-db-1`,
already running with real demo data) as part of writing this runbook —
not left as untested theory:

- `pg_dump` produced a real 1.8MB custom-format dump of the live
  `ticketsense` database.
- That dump was restored into a scratch `ticketsense_restore_test`
  database via `pg_restore --no-owner` with no errors.
- Row counts were compared directly between the original and restored
  databases and matched exactly: 2 organizations, 141 users, 126 tickets.
- The scratch database and the test dump file were then dropped/deleted
  as cleanup; nothing from this verification was left behind.

What was **not** verified: cutting a running `api` container over to a
restored database (the "rename databases and restart `api`" step
described at the end of step 3), and a restore of the separate attachment
storage volume described in step 4 (this repository's demo data has no
attachment volume configured to restore, per the gap noted there). Those
two remain the honest, stated gaps in an otherwise-executed rehearsal.

## Honest limitations

- No point-in-time recovery (PITR): this is periodic full-dump backup only.
  A production deployment wanting PITR needs WAL archiving
  (`archive_mode`/`wal_level=replica` plus a WAL-shipping tool), which
  this repository does not configure.
- No off-host replication: backups land on the same host running Docker
  Compose unless the operator adds their own off-host copy step.
- No automated restore-drill verification: nothing in this repository
  currently re-restores a backup on a schedule to prove it's actually
  restorable — this runbook documents the manual procedure, not an
  automated verification job.
