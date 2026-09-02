#!/bin/bash
# Create virtual floppy disk with autounattend.xml for automated Windows installation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLOPPY_FILE="$SCRIPT_DIR/windows-autounattend.vfd"
AUTOUNATTEND_FILE="$SCRIPT_DIR/autounattend.xml"

echo "🔧 Creating Windows autounattend floppy disk..."

# Check if autounattend.xml exists
if [ ! -f "$AUTOUNATTEND_FILE" ]; then
    echo " Error: autounattend.xml not found at $AUTOUNATTEND_FILE"
    exit 1
fi

# Create a 1.44MB floppy image
dd if=/dev/zero of="$FLOPPY_FILE" bs=1024 count=1440 2>/dev/null

# Format as FAT12
mkfs.vfat -F 12 "$FLOPPY_FILE" >/dev/null 2>&1

# Copy autounattend.xml to floppy
mcopy -i "$FLOPPY_FILE" "$AUTOUNATTEND_FILE" ::/autounattend.xml

echo "✅ Floppy disk created: $FLOPPY_FILE"
echo "   Size: $(du -h "$FLOPPY_FILE" | cut -f1)"
echo "   Contents: autounattend.xml"

