#!/bin/bash
# Automated SSH setup using sshpass
# Usage: PVE_ROOT_PASSWORD=yourpassword bash tools/setup_ssh_auto.sh

set -euo pipefail

PVE_HOST="${PVE_HOST:-192.168.0.10}"
PVE_USER="${PVE_USER:-root}"

# Check if password is provided
if [ -z "${PVE_ROOT_PASSWORD:-}" ]; then
    echo "❌ PVE_ROOT_PASSWORD environment variable not set"
    echo ""
    echo "Usage:"
    echo "  PVE_ROOT_PASSWORD=yourpassword bash tools/setup_ssh_auto.sh"
    echo ""
    echo "Or manually:"
    echo "  ssh-copy-id -o StrictHostKeyChecking=no root@192.168.0.10"
    exit 1
fi

echo "════════════════════════════════════════════════════════════════╗"
echo "║  Automated SSH Key Setup                                       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Generate SSH key if needed
if [ ! -f ~/.ssh/id_rsa ]; then
    echo "Generating SSH key..."
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N "" -q
    echo "✅ SSH key generated"
else
    echo "✅ SSH key exists"
fi

echo ""
echo "Copying SSH key to PVE ($PVE_HOST)..."

# Use sshpass to copy key
export SSHPASS="$PVE_ROOT_PASSWORD"
sshpass -e ssh-copy-id -o StrictHostKeyChecking=no -i ~/.ssh/id_rsa.pub ${PVE_USER}@${PVE_HOST}

echo ""
echo "Testing SSH connection..."
if ssh -o StrictHostKeyChecking=no -o BatchMode=yes ${PVE_USER}@${PVE_HOST} "echo '✅ SSH connection successful'" 2>/dev/null; then
    echo ""
    echo "════════════════════════════════════════════════════════════════╗"
    echo "║  SSH Setup Complete!                                           ║"
    echo "════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "You can now run automated Windows installation:"
    echo "  python3 tools/auto_install_windows.py"
else
    echo "❌ SSH connection failed"
    echo "Please verify your PVE root password and try again."
    exit 1
fi
