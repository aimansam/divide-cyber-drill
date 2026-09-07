#!/bin/bash
# OxBlood Portal - Revert Script
# Restores database and code from a backup

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <backup_path>"
  echo ""
  echo "Available backups:"
  ls -d /tmp/oxblood_backups/backup_* 2>/dev/null || echo "  No backups found"
  exit 1
fi

BACKUP_PATH="$1"

if [ ! -d "$BACKUP_PATH" ]; then
  echo "ERROR: Backup path not found: $BACKUP_PATH"
  exit 1
fi

echo "============================================"
echo "  OxBlood Portal Revert"
echo "============================================"
echo ""
echo "WARNING: This will overwrite current data!"
echo "Backup source: $BACKUP_PATH"
echo ""
read -p "Are you sure? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
  echo "Revert cancelled."
  exit 0
fi

echo ""

# 1. Restore database
echo "1. Restoring database..."
if [ -f "$BACKUP_PATH/database.sql" ]; then
  docker compose -f /DATA/Storage/docker/divide-cyber-drill/deploy/docker-compose.yml exec -T postgres psql -U divide divide < "$BACKUP_PATH/database.sql"
  echo "   ✓ Database restored"
else
  echo "   ⚠ No database backup found, skipping"
fi

# 2. Restore portal code
echo "2. Restoring portal code..."
if [ -d "$BACKUP_PATH/portal_app" ]; then
  cp -r "$BACKUP_PATH/portal_app/"* /DATA/Storage/docker/divide-cyber-drill/services/portal/app/
  echo "   ✓ Portal code restored"
else
  echo "   ⚠ No portal backup found, skipping"
fi

# 3. Restore API routers
echo "3. Restoring API routers..."
if [ -d "$BACKUP_PATH/api_routers" ]; then
  cp -r "$BACKUP_PATH/api_routers/"* /DATA/Storage/docker/divide-cyber-drill/services/api/app/routers/
  echo "   ✓ API routers restored"
else
  echo "   ⚠ No API routers backup found, skipping"
fi

echo ""
echo "============================================"
echo "  Revert Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Restart portal: docker compose -f deploy/docker-compose.yml restart portal"
echo "  2. Restart API: docker compose restart api"
echo ""
echo "Run these commands to complete the revert."
