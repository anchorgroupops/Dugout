#!/bin/bash
# Container-side deploy wrapper.
# Runs inside the sharks_api Docker container; SSHes to the Pi host to execute
# the native pi-deploy.sh (which has access to docker compose and the project dir).
#
# Requires:
#   DEPLOY_SSH_KEY_B64  — base64-encoded Pi SSH private key (set in .env + docker-compose)
#   pi-host             — resolves via extra_hosts:host-gateway in docker-compose
set -e

if [ -z "${DEPLOY_SSH_KEY_B64}" ]; then
  echo "ERROR: DEPLOY_SSH_KEY_B64 is not set — cannot deploy via SSH" >&2
  exit 1
fi

# Write the SSH key to a temp file with strict permissions
KEY_FILE=$(mktemp)
printf '%s' "${DEPLOY_SSH_KEY_B64}" | base64 -d > "${KEY_FILE}"
chmod 600 "${KEY_FILE}"

cleanup() { rm -f "${KEY_FILE}"; }
trap cleanup EXIT

echo "SSHing to pi-host to run pi-deploy.sh..."
ssh -i "${KEY_FILE}" \
    -o StrictHostKeyChecking=no \
    -o ConnectTimeout=15 \
    -o BatchMode=yes \
    joelycannoli@pi-host \
    "bash /home/joelycannoli/dugout/scripts/pi-deploy.sh"
