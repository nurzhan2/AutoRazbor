#!/bin/bash
# deploy.sh - run this on the VPS to deploy/update the project
set -e

echo "=== EuroRazbor Deploy ==="

# Pull latest code
git pull origin main

# Rebuild and restart container
docker compose down
docker compose build --no-cache
docker compose up -d

echo "=== Done! ==="
echo "Site running at http://$(curl -s ifconfig.me)"
docker compose logs --tail=20
