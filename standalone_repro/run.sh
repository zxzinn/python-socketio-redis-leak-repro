#!/usr/bin/env bash
# End-to-end repro: start proxy + 2-worker gunicorn, send N garbage rounds,
# show server-side subscribe count after each round. Requires a real Redis
# on 127.0.0.1:6379.

set -e

cd "$(dirname "$0")"

ROUNDS="${ROUNDS:-10}"
GAP="${GAP:-3}"

# Sanity: real redis must be reachable
redis-cli -p 6379 ping >/dev/null || { echo "no redis on :6379"; exit 1; }

# Clean any prior state
redis-cli -p 6379 -n 0 CLIENT KILL TYPE pubsub >/dev/null 2>&1 || true
redis-cli -p 6379 -n 0 CLIENT KILL TYPE normal >/dev/null 2>&1 || true

cleanup() {
    pkill -f "standalone_repro/proxy.py" 2>/dev/null || true
    pkill -f "standalone_repro.app" 2>/dev/null || true
    pkill -f "gunicorn standalone_repro.app" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== starting proxy on :6391 ==="
python3 proxy.py > /tmp/repro_proxy.log 2>&1 &
PROXY_PID=$!
sleep 2
if ! kill -0 "$PROXY_PID" 2>/dev/null; then
    echo "proxy died:"; cat /tmp/repro_proxy.log; exit 1
fi
echo "proxy pid: $PROXY_PID"

echo "=== starting gunicorn (2 workers, uvicorn) ==="
cd ..
uv run --with python-socketio==5.8.0 --with "redis>=5,<6" --with uvicorn --with gunicorn \
    gunicorn standalone_repro.app:app \
    --bind 127.0.0.1:0 \
    -k uvicorn.workers.UvicornH11Worker \
    --workers 2 \
    > /tmp/repro_gun.log 2>&1 &
GUN_PID=$!

# Wait for both workers to finish startup
for i in $(seq 1 60); do
    n=$(grep -c "Application startup complete" /tmp/repro_gun.log 2>/dev/null)
    n=${n:-0}
    if [ "$n" -ge 2 ] 2>/dev/null; then break; fi
    sleep 1
done
echo "gunicorn ready"

# Initial state
sleep 2
INIT=$(redis-cli -p 6379 CLIENT LIST | grep -c subscribe)
echo "initial server-side subscribe count: $INIT"

for i in $(seq 1 "$ROUNDS"); do
    kill -USR1 "$PROXY_PID"
    sleep "$GAP"
    SUBS=$(redis-cli -p 6379 CLIENT LIST | grep -c subscribe)
    echo "after garbage #$i: subscribe=$SUBS"
done

echo
echo "=== final ==="
echo "subscribe rows on server (cmd | age | idle):"
redis-cli -p 6379 CLIENT LIST | grep subscribe | awk '{
    for (i=1;i<=NF;i++) {
        if ($i ~ /^age=|^idle=|^cmd=/) printf "%s ", $i
    }
    print ""
}'
