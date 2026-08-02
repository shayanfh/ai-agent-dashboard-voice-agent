#!/bin/sh
set -eu

RECORDING_DIRECTORY="${ASTERISK_RECORDING_DIRECTORY:-/var/spool/asterisk/monitor/ai-agent}"
UPLOADER="${ASTERISK_RECORDING_UPLOADER:-/usr/local/bin/upload-asterisk-recording.sh}"

find "$RECORDING_DIRECTORY" -maxdepth 1 -type f -name '*.wav' -mmin +1 -print |
while IFS= read -r recording_file; do
  if [ -e "${recording_file}.uploaded" ]; then
    continue
  fi
  filename=$(basename -- "$recording_file")
  linked_id=${filename%.wav}
  "$UPLOADER" "$recording_file" "$linked_id" || true
done
