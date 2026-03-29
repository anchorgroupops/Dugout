#!/bin/bash
# =============================================================================
# Dugout — Oracle Cloud VM Bootstrap Script
# =============================================================================
# Run this ON the Oracle Cloud VM after SSH'ing in for the first time.
# Installs Docker, clones the repo, and starts the Dugout stack.
#
# Usage:
#   ssh -i infra/oracle/dugout-oci.pem ubuntu@<VM_PUBLIC_IP> 'bash -s' < scripts/oci_bootstrap.sh
#   OR
#   ssh into the VM, then: curl -sSL <raw-github-url> | bash
# =============================================================================

set -euo pipefail

echo "============================================"
echo "  Dugout — Oracle Cloud VM Setup"
echo "============================================"
echo ""

# ── 1. System updates ────────────────────────────────────────────────────────
echo "[1/6] Updating system packages..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq

# ── 2. Install Docker ────────────────────────────────────────────────────────
echo "[2/6] Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "  Docker installed. You may need to log out and back in for group changes."
else
    echo "  Docker already installed."
fi

# Install Docker Compose plugin if not present
if ! docker compose version &>/dev/null 2>&1; then
    echo "  Installing Docker Compose plugin..."
    sudo apt-get install -y -qq docker-compose-plugin
fi

# ── 3. Open firewall ports ───────────────────────────────────────────────────
echo "[3/6] Opening firewall ports (80, 443, 3000)..."
# Oracle Linux / Ubuntu use iptables by default on OCI
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 3000 -j ACCEPT 2>/dev/null || true
# Persist rules
sudo sh -c 'iptables-save > /etc/iptables/rules.v4' 2>/dev/null || \
    sudo netfilter-persistent save 2>/dev/null || true
echo "  Firewall rules added."
echo "  NOTE: You also need to add Ingress Rules in the OCI Console:"
echo "    VCN → Subnet → Security List → Add: 0.0.0.0/0, TCP, port 3000"

# ── 4. Clone the repository ─────────────────────────────────────────────────
echo "[4/6] Cloning Dugout repository..."
DUGOUT_DIR="$HOME/dugout"
if [ -d "$DUGOUT_DIR" ]; then
    echo "  Directory exists, pulling latest..."
    cd "$DUGOUT_DIR" && git pull origin main
else
    git clone https://github.com/anchorgroupops/Softball.git "$DUGOUT_DIR"
    cd "$DUGOUT_DIR"
fi

# ── 5. Environment file ─────────────────────────────────────────────────────
echo "[5/6] Setting up environment..."
if [ ! -f "$DUGOUT_DIR/.env" ]; then
    cp "$DUGOUT_DIR/.env.example" "$DUGOUT_DIR/.env"
    echo ""
    echo "  *** IMPORTANT: Edit $DUGOUT_DIR/.env with your credentials ***"
    echo "  Required:"
    echo "    GC_EMAIL=fly386@gmail.com"
    echo "    GC_PASSWORD=<your-password>"
    echo "    GC_IMAP_APP_PASSWORD=<google-app-password>"
    echo "    GC_TEAM_ID=NuGgx6WvP7TO"
    echo "    GC_SEASON_SLUG=2026-spring-sharks"
    echo "    TEAM_SLUG=sharks"
    echo "    TEAM_NAME=The Sharks"
    echo ""
else
    echo "  .env already exists, skipping."
fi

# ── 6. Start the stack ──────────────────────────────────────────────────────
echo "[6/6] Starting Dugout stack..."
cd "$DUGOUT_DIR"

# Authenticate with GHCR if images are pre-built
if [ -n "${GITHUB_TOKEN:-}" ]; then
    echo "$GITHUB_TOKEN" | docker login ghcr.io -u anchorgroupops --password-stdin
fi

# Pull or build and start
docker compose -f docker-compose.dugout.yml up -d --build

echo ""
echo "============================================"
echo "  Dugout is starting!"
echo "============================================"
echo ""
echo "  Dashboard:  http://$(curl -s ifconfig.me):3000"
echo "  API health: http://$(curl -s ifconfig.me):3000/api/health"
echo ""
echo "  Next steps:"
echo "    1. Edit .env with your credentials (if not done)"
echo "    2. Add OCI Security List ingress rule for port 3000"
echo "    3. Update Cloudflare tunnel: dugout.joelycannoli.com -> http://<this-ip>:3000"
echo "    4. Monitor logs: docker logs -f dugout_sync"
echo ""
