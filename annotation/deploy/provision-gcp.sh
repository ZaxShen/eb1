#!/usr/bin/env bash
# Provision the GCP infrastructure for the annotation site. Run MANUALLY by the
# operator after `gcloud auth login` and setting the variables below. Every step
# is echoed before it runs. Nothing here is idempotent-safe to re-run blindly —
# read RUNBOOK.md first.
#
#   Edit the variables, then:  annotation/deploy/provision-gcp.sh
set -euo pipefail

# ---- Configuration (edit these) --------------------------------------------
PROJECT_ID="${PROJECT_ID:-my-eb1-project}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-eb1-annotation}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-medium}"
DISK_SIZE_GB="${DISK_SIZE_GB:-50}"
STATIC_IP_NAME="${STATIC_IP_NAME:-eb1-annotation-ip}"
FIREWALL_NAME="${FIREWALL_NAME:-eb1-annotation-web}"
GCS_BACKUP_BUCKET="${GCS_BACKUP_BUCKET:-eb1-annotation-backups}"
# ----------------------------------------------------------------------------

run() {
  echo "+ $*"
  "$@"
}

echo "== Provisioning annotation site infra in project $PROJECT_ID =="

echo "-- Enable the Compute Engine API"
run gcloud services enable compute.googleapis.com --project "$PROJECT_ID"

echo "-- Reserve a regional static external IP"
run gcloud compute addresses create "$STATIC_IP_NAME" \
  --project "$PROJECT_ID" --region "$REGION"

STATIC_IP="$(gcloud compute addresses describe "$STATIC_IP_NAME" \
  --project "$PROJECT_ID" --region "$REGION" --format='get(address)')"

echo "-- Open HTTP/HTTPS in the firewall"
run gcloud compute firewall-rules create "$FIREWALL_NAME" \
  --project "$PROJECT_ID" \
  --direction INGRESS --action ALLOW \
  --rules tcp:80,tcp:443 \
  --source-ranges 0.0.0.0/0 \
  --target-tags "$VM_NAME"

echo "-- Create the VM (Debian 12 + Docker via startup script)"
run gcloud compute instances create "$VM_NAME" \
  --project "$PROJECT_ID" --zone "$ZONE" \
  --machine-type "$MACHINE_TYPE" \
  --image-family debian-12 --image-project debian-cloud \
  --boot-disk-size "${DISK_SIZE_GB}GB" --boot-disk-type pd-balanced \
  --address "$STATIC_IP" \
  --tags "$VM_NAME" \
  --metadata startup-script='#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker'

echo "-- Create the GCS backup bucket"
run gcloud storage buckets create "gs://${GCS_BACKUP_BUCKET}" \
  --project "$PROJECT_ID" --location "$REGION" --uniform-bucket-level-access

echo "-- Grant the VM's default compute service account write access to the bucket"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='get(projectNumber)')"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
run gcloud storage buckets add-iam-policy-binding "gs://${GCS_BACKUP_BUCKET}" \
  --member "serviceAccount:${COMPUTE_SA}" \
  --role roles/storage.objectAdmin

echo
echo "== Done. Static IP for DuckDNS: $STATIC_IP =="
echo "Point your DuckDNS subdomain (SITE_DOMAIN) at $STATIC_IP, then follow RUNBOOK.md."
