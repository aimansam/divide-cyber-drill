#!/bin/bash
# Download cloud images for automated template creation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES_DIR="$SCRIPT_DIR/cloud-images"

mkdir -p "$IMAGES_DIR"
cd "$IMAGES_DIR"

echo "📥 Downloading Debian cloud image..."
if [ ! -f debian-cloud.qcow2 ]; then
    wget -q --show-progress \
        https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2 \
        -O debian-cloud.qcow2
    echo "✅ Debian cloud image downloaded"
else
    echo "✅ Debian cloud image already exists"
fi

echo ""
echo "Cloud images ready in: $IMAGES_DIR"
ls -lh "$IMAGES_DIR"
