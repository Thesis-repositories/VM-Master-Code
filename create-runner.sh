#!/bin/bash

source /home/master/code/.env

ORG_URL="https://github.com/${ORG}"

#generate a jwt
JWT=$( ./generate-jwt.sh ${CLIENT_ID} ${KEY_PATH} )

RESPONSE=$( curl --request POST \
--url "https://api.github.com/app/installations/${INSTALLATION_ID}/access_tokens" \
--header "Accept: application/vnd.github+json" \
--header "Authorization: Bearer ${JWT}" \
--header "X-GitHub-Api-Version: 2026-03-10" )

INSTALLATION_TOKEN=$(echo "$RESPONSE" | jq -r '.token')

RESPONSE=$( curl -L \
  -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${INSTALLATION_TOKEN}" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
 https://api.github.com/orgs/${ORG}/actions/runners/registration-token )

REGISTRATION_TOKEN=$(echo "$RESPONSE" | jq -r '.token')

echo $REGISTRATION_TOKEN
