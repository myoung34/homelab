#!/bin/bash
sleep 30
rm $1

SLACK_WEBHOOK_URL=$(cat /config/secrets.yaml | grep slack_webhook_url | awk '{print $2}' | sed "s/'//g")
curl -XPOST "${SLACK_WEBHOOK_URL}" -d "{\"message\": \"Hass backup to minio complete.\"}"
