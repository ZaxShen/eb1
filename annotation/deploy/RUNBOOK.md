# Annotation Site — GCP Deployment Runbook

End-to-end steps to run the eb1 annotation site on a single GCP VM (Debian 12 +
Docker + docker compose) with Caddy-terminated TLS and Google SSO. Everything
here is **operator-run and manual** — nothing in the repo auto-deploys.

Shape: one `e2-medium` VM running compose services `postgres` (internal only),
`backend` (FastAPI, internal only), and `caddy` (TLS + static frontend + `/api`
reverse proxy). Expected cost ~$30–40/mo — a multi-month campaign fits inside
the $300 new-user free credit.

All paths below are relative to the repo root on your workstation unless a step
says "on the VM".

---

## 1. GCP project, billing, and budget alerts

1. Create (or pick) a GCP project and note its **Project ID**.
2. **Billing**: link a billing account (required for the $300 free credit).
3. **Budget alerts** (Console — budgets can't be trusted to a script):
   Console → **Billing → Budgets & alerts → Create budget**. Scope to the
   project, set the amount to **$300**, and add alert thresholds at **50%,
   75%, and 90%**. These only notify — they do not cap spend.

## 2. Provision infrastructure

1. `gcloud auth login` and `gcloud config set project <PROJECT_ID>`.
2. Open `annotation/deploy/provision-gcp.sh` and edit the variables at
   the top (`PROJECT_ID`, `REGION`, `ZONE`, `VM_NAME`, `MACHINE_TYPE`,
   `DISK_SIZE_GB`, `STATIC_IP_NAME`, `FIREWALL_NAME`, `GCS_BACKUP_BUCKET`).
3. Run it: `annotation/deploy/provision-gcp.sh`. It enables the Compute
   API, reserves a static IP, opens tcp:80/443, creates the VM (Docker installed
   via startup script), creates the GCS backup bucket, grants the VM's default
   compute service account `roles/storage.objectAdmin` on the bucket, and prints
   the **static IP**.
4. Note the printed static IP for the next step.

## 3. DNS (DuckDNS)

1. Sign in at <https://www.duckdns.org> and create a subdomain, e.g.
   `eb1-annotate`.
2. Set its IP to the static IP from step 2 and save.
3. Confirm: `dig +short eb1-annotate.duckdns.org` returns that IP. This is your
   `SITE_DOMAIN`.

## 4. Google OAuth client

SSO reuses the app's existing in-app Google sign-in (public client ID, no
secret). Create the production client in the Console:

1. Console → **APIs & Services → OAuth consent screen**: configure (External),
   add yourself as a test user (or publish), and save.
2. Console → **APIs & Services → Credentials → Create credentials → OAuth client
   ID → Web application**.
3. Under **Authorized JavaScript origins** add `https://$SITE_DOMAIN` (e.g.
   `https://eb1-annotate.duckdns.org`). No redirect URI and no client secret are
   needed.
4. Copy the **Client ID** — it goes in both `GOOGLE_CLIENT_ID` and
   `VITE_GOOGLE_CLIENT_ID`.

## 5. Deploy

1. Get the repo onto the VM: `gcloud compute ssh <VM_NAME> --zone <ZONE>`, then
   `git clone <repo-url>` (or `rsync` your checkout). `cd` into
   `annotation/deploy`.
2. Create the env file: `cp .env.example .env` and fill in every value —
   `SITE_DOMAIN`, a long random `POSTGRES_PASSWORD` (mirror it inside
   `EB1_ANNOTATION_DSN`), the OAuth `GOOGLE_CLIENT_ID` / `VITE_GOOGLE_CLIENT_ID`,
   the annotator `ALLOWED_EMAILS`, and `GCS_BACKUP_BUCKET`.
3. Validate: `docker compose --env-file .env -f docker-compose.prod.yml config -q`.
4. Bring it up:
   `docker compose --env-file .env -f docker-compose.prod.yml up -d --build`.
   The first build takes a few minutes. Caddy fetches a Let's Encrypt cert for
   `SITE_DOMAIN` automatically once DNS resolves.
5. Verify: browse to `https://$SITE_DOMAIN`, sign in with an allowlisted Google
   account.

> Changing `VITE_GOOGLE_CLIENT_ID` requires rebuilding the frontend image
> (`docker compose ... up -d --build caddy`) because Vite inlines it at build
> time.

## 6. Load the annotation data

The site is populated with the **sampled** annotation subset (not the full
1.85M-conversation corpus). Build/restore it from your workstation where the
data already lives.

- The sampling worklist is produced by `annotation/sampling/` (e.g.
  `python -m annotation.sampling.superdialseg`); ingestion into a local Postgres
  uses `annotation.ingest.run` (see `annotation/README.md`).
- Dump the sampled DB locally (custom format):
  `docker exec eb1-annotation-pg pg_dump -U eb1 -Fc eb1_annotation > sample.dump`.
- Copy it to the VM (`gcloud compute scp sample.dump <VM_NAME>:~ --zone <ZONE>`).
- Restore into the running prod Postgres over the internal network:
  `docker compose -f docker-compose.prod.yml exec -T postgres \
   pg_restore -U eb1 -d eb1_annotation --clean --if-exists < sample.dump`.

## 7. Add / remove an annotator

1. Edit `ALLOWED_EMAILS` in `.env` (comma-separated, case-insensitive).
2. Apply it (backend reads the var at startup):
   `docker compose --env-file .env -f docker-compose.prod.yml up -d backend`.
   No rebuild needed — only the backend restarts. Removing an email revokes
   access on the next request.

## 8. Backups and restore drill

1. On the VM, schedule the daily upload with cron (backups go to
   `gs://$GCS_BACKUP_BUCKET/`, keyless via the VM's compute SA):
   ```
   # crontab -e  (adjust the repo path)
   0 3 * * * GCS_BACKUP_BUCKET=<bucket> /path/to/repo/annotation/deploy/backup-gcs.sh >> /var/log/eb1-backup.log 2>&1
   ```
2. **Retention** is a bucket lifecycle rule, not scripted deletion. Set it once:
   ```
   printf '{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}' > /tmp/lifecycle.json
   gcloud storage buckets update gs://<bucket> --lifecycle-file=/tmp/lifecycle.json
   ```
3. **Restore drill** (do this at least once): pick a recent object, then
   ```
   gcloud storage cp gs://<bucket>/<object>.dump ./restore.dump
   docker compose -f docker-compose.prod.yml exec -T postgres \
     pg_restore -U eb1 -d eb1_annotation --clean --if-exists < restore.dump
   ```
   Confirm the row counts / a spot-checked conversation match expectations.

## 9. Updating the deployment

1. On the VM, `git pull` (or re-`rsync`) in the repo.
2. Rebuild + restart:
   `docker compose --env-file .env -f docker-compose.prod.yml up -d --build`.
3. Compose recreates only changed services; the Postgres volume and Caddy certs
   persist across updates.

## 10. Teardown

When the campaign ends:

1. Take a final backup and confirm it landed in the bucket
   (`annotation/deploy/backup-gcs.sh`).
2. Delete the VM: `gcloud compute instances delete <VM_NAME> --zone <ZONE>`.
3. Release the static IP:
   `gcloud compute addresses delete <STATIC_IP_NAME> --region <REGION>`.
4. Optionally delete the firewall rule: `gcloud compute firewall-rules delete
   <FIREWALL_NAME>`.
5. **Keep the GCS bucket** (it holds the backups) — or delete it explicitly once
   the dumps are archived elsewhere.
6. Remove the DuckDNS subdomain if no longer needed.
