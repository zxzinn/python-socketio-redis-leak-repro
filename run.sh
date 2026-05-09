#!/usr/bin/env bash
# End-to-end repro:
#   1. start a tcp proxy on 6391 forwarding to redis on 6379
#   2. start gunicorn (2 uvicorn workers) running app.py against the proxy
#   3. open a few socket.io client sessions to trigger manager.initialize()
#      on every worker
#   4. send N rounds of `SIGUSR1` to the proxy; each round writes invalid
#      RESP bytes to all client writers without closing the socket, which
#      makes the manager's listen path raise RedisError, swap clients, and
#      orphan the previous PubSub on the redis server
#   5. count cmd=subscribe rows on redis after each round
#
# Requires a real Redis on 127.0.0.1:6379, plus uv.

cd "$(dirname "$0")"

ROUNDS="${ROUNDS:-10}"
GAP="${GAP:-3}"
PORT="${PORT:-8765}"

if ! redis-cli -p 6379 ping >/dev/null 2>&1; then
    echo "no redis on :6379"; exit 1
fi
redis-cli -p 6379 CLIENT KILL TYPE pubsub >/dev/null 2>&1 || true
redis-cli -p 6379 CLIENT KILL TYPE normal >/dev/null 2>&1 || true

cleanup() {
    [ -n "${PROXY_PID:-}" ] && kill -9 "$PROXY_PID" 2>/dev/null
    [ -n "${GUN_PID:-}" ] && kill -9 "$GUN_PID" 2>/dev/null
    pkill -9 -f "$(pwd)/proxy.py" 2>/dev/null
    pkill -9 -f "gunicorn app:app" 2>/dev/null
}
trap cleanup EXIT

echo "=== starting proxy 127.0.0.1:6391 -> 127.0.0.1:6379 ==="
python3 proxy.py > /tmp/repro_proxy.log 2>&1 &
PROXY_PID=$!
sleep 2
if ! kill -0 "$PROXY_PID" 2>/dev/null; then
    echo "proxy died:"; cat /tmp/repro_proxy.log; exit 1
fi
echo "proxy pid: $PROXY_PID"

echo "=== starting gunicorn (2 workers) on :$PORT ==="
uv run --with python-socketio==5.8.0 --with "redis>=5,<6" \
       --with uvicorn --with gunicorn \
    gunicorn app:app \
    --bind "127.0.0.1:$PORT" \
    -k uvicorn.workers.UvicornH11Worker \
    --workers 2 \
    > /tmp/repro_gun.log 2>&1 &
GUN_PID=$!

# Wait for both workers' "Application startup complete"
ready=0
for i in $(seq 1 60); do
    n=$(grep -c "Application startup complete" /tmp/repro_gun.log 2>/dev/null)
    [ "$n" = "" ] && n=0
    if [ "$n" -ge 2 ]; then ready=1; break; fi
    sleep 1
done
if [ "$ready" != "1" ]; then
    echo "gunicorn never became ready; log:"
    tail -20 /tmp/repro_gun.log
    exit 1
fi
echo "gunicorn ready"

echo "=== triggering manager.initialize() via real socket.io client connects ==="
uv run --with python-socketio==5.8.0 --with aiohttp --with websocket-client \
    python trigger_init.py "http://127.0.0.1:$PORT" 8 \
    > /tmp/repro_trigger.log 2>&1 || true
sleep 2

INIT=$(redis-cli -p 6379 CLIENT LIST | grep -c "cmd=subscribe")
echo "initial server-side subscribe count: $INIT"

for i in $(seq 1 "$ROUNDS"); do
    kill -USR1 "$PROXY_PID"
    sleep "$GAP"
    SUBS=$(redis-cli -p 6379 CLIENT LIST | grep -c "cmd=subscribe")
    echo "after garbage #$i: subscribe=$SUBS"
done

echo
echo "=== final ==="
echo "subscribe rows on server (cmd | age | idle):"
redis-cli -p 6379 CLIENT LIST | grep "cmd=subscribe" | awk '{
    for (i=1;i<=NF;i++) {
        if ($i ~ /^age=|^idle=|^cmd=/) printf "%s ", $i
    }
    print ""
}'
