#!/usr/bin/env bash
# restart-down-services.sh — Restart the 6 down fleet services on Oracle1
# Run this on Oracle1 (<BOAT_IP>) as the ubuntu user

set -euo pipefail

SERVICES=(
    "dashboard:4046"
    "nexus:4047"
    "harbor:4050"
    "service-guard:8899"
    "task-queue:8900"
    "steward:8901"
)

LOGDIR="/tmp/fleet-restart-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOGDIR"

for svc in "${SERVICES[@]}"; do
    name="${svc%%:*}"
    port="${svc##*:}"
    log="$LOGDIR/${name}.log"
    
    echo "[$name] Checking port $port..."
    if nc -z 127.0.0.1 "$port" 2>/dev/null; then
        echo "  [$name] Already up on port $port"
        continue
    fi
    
    echo "  [$name] Down. Attempting restart..."
    
    # Try systemd first
    if systemctl is-active --quiet "$name" 2>/dev/null; then
        echo "  [$name] systemctl restart $name"
        sudo systemctl restart "$name" 2>>"$log" || true
    elif systemctl is-active --quiet "fleet-$name" 2>/dev/null; then
        echo "  [$name] systemctl restart fleet-$name"
        sudo systemctl restart "fleet-$name" 2>>"$log" || true
    else
        echo "  [$name] No systemd unit found. Manual restart needed."
        echo "  [$name] Check supervisor configs in /etc/supervisor/conf.d/"
    fi
    
    sleep 2
    if nc -z 127.0.0.1 "$port" 2>/dev/null; then
        echo "  [$name] ✅ Restarted successfully"
    else
        echo "  [$name] ❌ Still down. See $log"
    fi
done

echo ""
echo "Restart log directory: $LOGDIR"
echo "If services are still down, check:"
echo "  - /var/log/fleet/ for application logs"
echo "  - systemctl status <service> for systemd errors"
echo "  - sudo supervisorctl status for supervisord-managed services"
