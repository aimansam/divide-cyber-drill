#!/bin/bash
# One-time SSH key setup for PVE automation
# Run this ONCE to enable automated Windows installation

set -euo pipefail

PVE_HOST="${PVE_HOST:-192.168.0.10}"
PVE_USER="${PVE_USER:-root}"

echo "════════════════════════════════════════════════════════════════╗"
echo "║  PVE SSH Key Setup (One-Time)                                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "This script sets up SSH keys for automated Windows installation."
echo "You'll need to enter your PVE root password ONCE."
echo ""

# Generate SSH key if it doesn't exist
if [ ! -f ~/.ssh/id_rsa ]; then
    echo "Generating SSH key pair..."
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N "" -q
    echo "✅ SSH key generated"
else
    echo "✅ SSH key already exists"
fi

echo ""
echo "Copying public key to PVE host ($PVE_HOST)..."
echo "Enter PVE root password when prompted:"
echo ""

# Copy public key to PVE
ssh-copy-id -o StrictHostKeyChecking=no -i ~/.ssh/id_rsa.pub ${PVE_USER}@${PVE_HOST}

echo ""
echo "Testing SSH connection..."
if ssh -o StrictHostKeyChecking=no -o BatchMode=yes ${PVE_USER}@${PVE_HOST} "echo 'SSH connection successful'" 2>/dev/null; then
    echo "✅ SSH connection working!"
    echo ""
    echo "════════════════════════════════════════════════════════════════╗"
    echo "║  SSH Setup Complete!                                           ║"
    echo "════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "You can now run automated Windows installation:"
    echo "  python3 tools/auto_install_windows.py"
    echo ""
else
    echo "❌ SSH connection failed"
    echo "Please check your PVE credentials and try again."
    exit 1
fi
