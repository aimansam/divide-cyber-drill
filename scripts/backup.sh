#!/bin/bash
# OxBlood Portal - Backup Script
# Creates backups of database and code for easy reverting

set -e

BACKUP_DIR="/tmp/oxblood_backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/backup_$TIMESTAMP"

echo "============================================"
echo "  OxBlood Portal Backup"
echo "============================================"
echo ""

# Create backup directory
mkdir -p "$BACKUP_PATH"

# 1. Database backup
echo "1. Backing up database..."
docker compose -f /DATA/Storage/docker/divide-cyber-drill/deploy/docker-compose.yml exec -T postgres pg_dump -U divide divide > "$BACKUP_PATH/database.sql"
echo "   ✓ Database backed up to $BACKUP_PATH/database.sql"

# 2. Portal code backup
echo "2. Backing up portal code..."
cp -r /DATA/Storage/docker/divide-cyber-drill/services/portal/app "$BACKUP_PATH/portal_app"
echo "   ✓ Portal code backed up"

# 3. API routers backup
echo "3. Backing up API routers..."
cp -r /DATA/Storage/docker/divide-cyber-drill/services/api/app/routers "$BACKUP_PATH/api_routers"
echo "   ✓ API routers backed up"

# 4. Export current drills
echo "4. Exporting current drills..."
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"sub":"admin","password":"adminpass123"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")
curl -s http://localhost:8000/api/v2/drills -H "X-Divide-Token: $TOKEN" > "$BACKUP_PATH/drills.json"
echo "   ✓ Drills exported"

# 5. Export current users
echo "5. Exporting current users..."
curl -s http://localhost:8000/api/v1/auth/users -H "X-Divide-Token: $TOKEN" > "$BACKUP_PATH/users.json" 2>/dev/null || echo "   ⚠ Users export skipped (endpoint may not exist)"

echo ""
echo "============================================"
echo "  Backup Complete!"
echo "============================================"
echo ""
echo "Backup location: $BACKUP_PATH"
echo ""
echo "To revert, run:"
echo "  bash /DATA/Storage/docker/divide-cyber-drill/scripts/revert.sh $BACKUP_PATH"
echo ""
echo "Files backed up:"
ls -lh "$BACKUP_PATH"/
