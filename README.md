# python-socketio AsyncRedisManager listen-path leak repro

Repro for https://github.com/miguelgrinberg/python-socketio/issues/1569

## What it shows

`AsyncRedisManager._redis_listen_with_retries` catches `RedisError`, swaps
`self.redis` and `self.pubsub` via `_redis_connect()`, and resubscribes.
The previous `Redis` and `PubSub` instances are discarded without
`await aclose()`. Their TCP sockets stay `ESTABLISHED` on the Redis server.

After N reconnects we observe N orphaned `cmd=subscribe` rows in
`CLIENT LIST`, all with `idle == age` (never used after creation).

## Run

```
cd standalone_repro
./run.sh
```

Requires:
- a real Redis on `127.0.0.1:6379`
- `uv`
- `gunicorn`/`uvicorn`/`python-socketio==5.8.0`/`redis>=5,<6` (uv installs them)

## What the script does

1. Starts a TCP proxy on `127.0.0.1:6391` that forwards to `127.0.0.1:6379`.
2. Starts gunicorn with 2 `uvicorn.workers.UvicornH11Worker` workers running
   `app.py`, which is a minimal ASGI app wiring a single `AsyncRedisManager`
   pointed at the proxy. The lifespan handler triggers `manager.initialize()`
   so the listen task is spawned at startup.
3. Sends `SIGUSR1` to the proxy 10 times, with 3-second gaps. Each `SIGUSR1`
   makes the proxy write invalid RESP bytes to all client writers without
   closing the socket. The manager's `pubsub.listen()` raises `RedisError`,
   `_redis_listen_with_retries` enters its except branch, sleeps with
   exponential backoff, then reconnects via `_redis_connect()`.
4. After each round, prints the count of `cmd=subscribe` rows on the real
   Redis server.

## Observed output

```
gunicorn ready
initial server-side subscribe count: 2
after garbage #1: subscribe=4
after garbage #2: subscribe=6
after garbage #3: subscribe=8
after garbage #4: subscribe=10
after garbage #5: subscribe=12
after garbage #6: subscribe=14
after garbage #7: subscribe=16
after garbage #8: subscribe=18
after garbage #9: subscribe=20
after garbage #10: subscribe=22
```

2 workers, +2 per round. 22 subscribe rows after 10 rounds, all with
`idle == age` and no client-side fd in `lsof` for any but the 2 active.

## Versions

- python-socketio 5.8.0 (also reproduces on 5.16.1)
- redis 5.x
- Python 3.13
