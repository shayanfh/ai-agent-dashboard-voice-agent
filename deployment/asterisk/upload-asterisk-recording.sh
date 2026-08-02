#!/bin/sh
set -eu

CONFIG_FILE="${ASTERISK_RECORDING_CONFIG:-/etc/asterisk/ai-agent-recording.conf}"
if [ ! -r "$CONFIG_FILE" ]; then
  echo "Recording upload config is not readable: $CONFIG_FILE" >&2
  exit 1
fi

# The config file is root-owned and contains only the variables documented in the example.
# shellcheck disable=SC1090
. "$CONFIG_FILE"

RECORDING_FILE="${1:-}"
LINKED_ID="${2:-}"

case "$LINKED_ID" in
  ""|*[!A-Za-z0-9_.-]*)
    echo "Invalid Asterisk linked ID" >&2
    exit 1
    ;;
esac

if [ ! -s "$RECORDING_FILE" ]; then
  echo "Recording file is missing or empty: $RECORDING_FILE" >&2
  exit 1
fi

: "${DASHBOARD_BACKEND_URL:?DASHBOARD_BACKEND_URL is required}"
: "${DASHBOARD_INTERNAL_API_KEY:?DASHBOARD_INTERNAL_API_KEY is required}"

curl --fail-with-body --silent --show-error \
  --retry 5 --retry-delay 2 --retry-all-errors \
  --connect-timeout 10 --max-time 300 \
  -H "X-Internal-API-Key: ${DASHBOARD_INTERNAL_API_KEY}" \
  -F "linked_id=${LINKED_ID}" \
  -F "recording=@${RECORDING_FILE};type=audio/wav" \
  "${DASHBOARD_BACKEND_URL%/}/api/v1/internal/voice/recordings/asterisk"

if [ "${DELETE_AFTER_UPLOAD:-false}" = "true" ]; then
  rm -f -- "$RECORDING_FILE"
  rm -f -- "${RECORDING_FILE}.uploaded"
else
  : > "${RECORDING_FILE}.uploaded"
fi
