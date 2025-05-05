#!/bin/bash
sleep 30
if [[ -f "$1" ]]; then
  rm "$1"
fi

SLACK_WEBHOOK_URL=$(cat /config/secrets.yaml | grep slack_webhook_url | awk '{print $2}' | sed "s/'//g")
dig hooks.zapier.com >/dev/null 2>&1 # sometimes this somehow fails unless you try to resolve it once before curl
curl -XPOST "${SLACK_WEBHOOK_URL}" -d "{\"message\": \"Hass backup to minio complete.\"}"
