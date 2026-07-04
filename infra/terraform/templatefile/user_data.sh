#!/bin/bash
set -euo pipefail

APP_NAME="ai-document-analyzer"
SOURCE_REPO_URL="${source_repo_url}"
SOURCE_REF="${source_ref}"
SOURCE_DIR="/opt/cloudtechnext/ai-document-analyzer"
RUNTIME_DIR="/opt/cloudtechnext/ai-document-analyzer/runtime"
LOCAL_IMAGE="ai-document-analyzer:cloudtechnext"

retry() {
  local attempts="$1"
  shift
  local delay=10
  local attempt
  for attempt in $(seq 1 "$attempts"); do
    if "$@"; then
      return 0
    fi
    if [ "$attempt" -eq "$attempts" ]; then
      return 1
    fi
    echo "Command failed on attempt $attempt/$attempts: $*"
    echo "Retrying in $delay seconds..."
    sleep "$delay"
    if [ "$delay" -lt 60 ]; then
      delay=$((delay * 2))
    fi
  done
}

use_reachable_base_images() {
  sed -i \
    -e 's#^FROM node:#FROM public.ecr.aws/docker/library/node:#' \
    -e 's#^FROM python:#FROM public.ecr.aws/docker/library/python:#' \
    "$SOURCE_DIR/Dockerfile"
}

dnf -y makecache
dnf -y install dnf-plugins-core firewalld curl git
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker
usermod -aG docker opc
systemctl enable --now firewalld
firewall-cmd --add-service=http --permanent
firewall-cmd --add-service=ssh --permanent
firewall-cmd --reload

rm -rf "$SOURCE_DIR"
mkdir -p "$(dirname "$SOURCE_DIR")"
git clone --depth=1 --branch "$SOURCE_REF" "$SOURCE_REPO_URL" "$SOURCE_DIR"
use_reachable_base_images
mkdir -p "$RUNTIME_DIR/data" "$RUNTIME_DIR/wallet" "$RUNTIME_DIR/keys" "$RUNTIME_DIR/logs"
chown -R opc:opc "$RUNTIME_DIR"

# The first public repository cut may not include the OCI SVG assets imported by LoginForm.
# Keep the installer deterministic by materializing simple monochrome icons before building.
mkdir -p "$SOURCE_DIR/apps/frontend/src/assets/oci"
ensure_oci_icon() {
  local path="$1"
  local label="$2"
  if [ -f "$path" ]; then
    return
  fi
  cat >"$path" <<SVG
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
  <rect class="st0" width="96" height="96" rx="18" fill="none"/>
  <path class="st1" fill="currentColor" d="M48 14c18.8 0 34 15.2 34 34S66.8 82 48 82 14 66.8 14 48 29.2 14 48 14Zm0 12c-12.2 0-22 9.8-22 22s9.8 22 22 22 22-9.8 22-22-9.8-22-22-22Zm0 10 13 12-13 12-13-12 13-12Z"/>
  <title>$label</title>
</svg>
SVG
}
ensure_oci_icon "$SOURCE_DIR/apps/frontend/src/assets/oci/autonomous-database.svg" "Autonomous Database"
ensure_oci_icon "$SOURCE_DIR/apps/frontend/src/assets/oci/generative-ai.svg" "Generative AI"
ensure_oci_icon "$SOURCE_DIR/apps/frontend/src/assets/oci/object-storage.svg" "Object Storage"

retry 5 docker build -t "$LOCAL_IMAGE" "$SOURCE_DIR"
docker rm -f "$APP_NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$APP_NAME" \
  --restart unless-stopped \
  -p 80:80 \
  -v "$RUNTIME_DIR/data:/app/apps/backend/data" \
  -v "$RUNTIME_DIR/wallet:/app/apps/backend/wallet" \
  -v "$RUNTIME_DIR/keys:/app/apps/backend/keys" \
  -v "$RUNTIME_DIR/logs:/app/apps/backend/logs" \
  "$LOCAL_IMAGE"

for attempt in $(seq 1 60); do
  if curl --fail --silent http://127.0.0.1/api/health >/dev/null; then
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    docker logs "$APP_NAME" >/home/opc/ai-document-analyzer-container.log 2>&1 || true
    exit 1
  fi
  sleep 5
done

cat >/home/opc/startup_info.txt <<'INFO'
AI Document Analyzer is ready.

Application URL: http://[PUBLIC-IP]
SSH user: opc
Container: ai-document-analyzer
Source: https://github.com/jgangini/ai-document-analyzer

Setup flow: waiting for CloudTechNext automation to configure ADB, wallet, Object Storage, Generative AI and SQL installation.
Persistent runtime: /opt/cloudtechnext/ai-document-analyzer/runtime

Useful commands:
  docker ps
  docker logs ai-document-analyzer
  sudo journalctl -u docker --no-pager
INFO

chown opc:opc /home/opc/startup_info.txt
mkdir -p /var/local
touch /var/local/userdata.done
cat /home/opc/startup_info.txt
