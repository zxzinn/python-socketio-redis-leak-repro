# python-socketio AsyncRedisManager listen-path leak repro

Repro for https://github.com/miguelgrinberg/python-socketio/issues/1569

When `_redis_listen_with_retries` catches a `RedisError`, it swaps
`self.redis` and `self.pubsub` via `_redis_connect()` without `await
aclose()`-ing the previous instances. Their TCP sockets stay
`ESTABLISHED` on the Redis server; they're effectively leaked until OS
keepalive eventually reaps them.

## Layout

```
standalone_repro/
├── app.py            ASGI socket.io server, single AsyncRedisManager via
│                     the documented public constructor
├── proxy.py          tcp proxy 127.0.0.1:6391 -> 127.0.0.1:6379; on
│                     SIGUSR1 writes invalid RESP bytes to all client
│                     writers without closing the socket
├── trigger_init.py   opens N socket.io client sessions to make every
│                     gunicorn worker call manager.initialize()
└── run.sh            orchestration: starts proxy + gunicorn (2 uvicorn
                      workers), triggers init, sends SIGUSR1 N times,
                      counts cmd=subscribe rows on the real redis
```

Nothing in this repro touches a private method of `AsyncRedisManager`,
`PubSub`, or `Redis`. The failure is induced purely by sending invalid
RESP over the network, which is the cleanest way to reach
`_redis_listen_with_retries`' except branch from outside the process.

## Run

```
cd standalone_repro
./run.sh
```

Requires a real Redis on `127.0.0.1:6379` and `uv`.

## Output

```
gunicorn ready
=== triggering manager.initialize() via real socket.io client connects ===
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

2 workers, +2 every round = 1 leak per worker per swap. The 22 final
`cmd=subscribe` rows all have `idle == age` (the underlying client
never used them again after the swap).

## Versions

- python-socketio 5.8.0 (also reproduces on 5.16.1)
- redis 5.x
- Python 3.13
