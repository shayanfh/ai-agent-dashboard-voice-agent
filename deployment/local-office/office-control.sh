#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_ROOT=${INSTALL_ROOT:-/opt/mozaic-office}
CONFIG_ROOT=${CONFIG_ROOT:-/etc/mozaic-office}
RUNTIME_DIR="$INSTALL_ROOT/runtime"
STATE_FILE="$CONFIG_ROOT/install.env"

[[ ${EUID} -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ -r $STATE_FILE ]] || { echo "Missing $STATE_FILE; run the installer first." >&2; exit 1; }
# shellcheck disable=SC1090
source "$STATE_FILE"

# Older installations do not yet have these values in install.env.
BOOTSTRAP_ADMIN_EMAIL=${BOOTSTRAP_ADMIN_EMAIL:-login@starvox.ai}
BOOTSTRAP_ADMIN_PASSWORD=${BOOTSTRAP_ADMIN_PASSWORD:-admin@mozaic}
BOOTSTRAP_COMPANY_NAME=${BOOTSTRAP_COMPANY_NAME:-Starvox Office}

compose() {
  docker compose --env-file "$RUNTIME_DIR/.env" -f "$RUNTIME_DIR/docker-compose.yml" "$@"
}

bootstrap_admin() {
  local script="$INSTALL_ROOT/voice-agent/deployment/local-office/bootstrap_admin.py"
  [[ -r $script ]] || { echo "Missing $script; update the voice-agent repository." >&2; return 1; }
  export BOOTSTRAP_ADMIN_EMAIL BOOTSTRAP_ADMIN_PASSWORD BOOTSTRAP_COMPANY_NAME
  export BOOTSTRAP_TIMEZONE="$TIMEZONE"
  compose exec -T \
    -e BOOTSTRAP_ADMIN_EMAIL \
    -e BOOTSTRAP_ADMIN_PASSWORD \
    -e BOOTSTRAP_COMPANY_NAME \
    -e BOOTSTRAP_TIMEZONE \
    api python - < "$script"
}

health() {
  local failed=0
  systemctl is-active --quiet asterisk || { echo "FAIL asterisk"; failed=1; }
  curl -fsS "http://${SERVER_IP}:8000/health" >/dev/null \
    && echo "OK   backend" || { echo "FAIL backend"; failed=1; }
  curl -fsS -H "X-Provisioner-API-Key: ${PROVISIONER_API_KEY}" \
    "http://127.0.0.1:9443/health" >/dev/null \
    && echo "OK   provisioner" || { echo "FAIL provisioner"; failed=1; }
  timeout 2 bash -c "</dev/tcp/${SERVER_IP}/7880" 2>/dev/null \
    && echo "OK   livekit" || { echo "FAIL livekit"; failed=1; }
  compose ps --status running
  return "$failed"
}

update() {
  local repository
  for repository in frontend backend voice-agent; do
    if [[ -n $(git -C "$INSTALL_ROOT/$repository" status --porcelain) ]]; then
      echo "Refusing to update: $INSTALL_ROOT/$repository has local changes." >&2
      exit 1
    fi
  done
  for repository in frontend backend voice-agent; do
    git -C "$INSTALL_ROOT/$repository" pull --ff-only
  done
  local assets="$INSTALL_ROOT/voice-agent/deployment/local-office"
  install -m 0644 "$assets/docker-compose.yml" "$RUNTIME_DIR/docker-compose.yml"
  install -m 0644 "$assets/provision_livekit.py" "$RUNTIME_DIR/provision_livekit.py"
  install -m 0644 "$assets/Dockerfile.frontend" \
    "$INSTALL_ROOT/frontend/Dockerfile.local-office"
  install -m 0755 "$assets/office-control.sh" /usr/local/sbin/mozaic-office
  compose build api celery-worker celery-beat frontend asterisk-provisioner voice-agent
  compose run --rm api alembic upgrade head
  compose up -d
  bootstrap_admin
  systemctl restart asterisk
  health
}

case ${1:-status} in
  status)
    systemctl --no-pager --full status asterisk || true
    compose ps
    ;;
  health) health ;;
  logs) compose logs --tail="${2:-200}" -f ;;
  restart)
    systemctl restart asterisk
    compose restart
    health
    ;;
  bootstrap-admin) bootstrap_admin ;;
  update) update ;;
  *)
    echo "Usage: mozaic-office {status|health|logs [lines]|restart|bootstrap-admin|update}" >&2
    exit 2
    ;;
esac
