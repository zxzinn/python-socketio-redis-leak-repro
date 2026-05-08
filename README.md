# python-socketio AsyncRedisManager reconnect leak repro

Minimal reproduction for a resource leak in `socketio.AsyncRedisManager`'s
reconnect path.

## What leaks

`AsyncRedisManager._redis_connect` reassigns `self.redis` and `self.pubsub`
to fresh instances without closing the previous ones:

```python
def _redis_connect(self):
    ...
    self.redis = module.Redis.from_url(self.redis_url, **self.redis_options)
    self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
    self.connected = True
```

The method is invoked by both reconnect paths:

- `_publish` calls it after the first failed publish
- `_redis_listen_with_retries` calls it after any `RedisError`

`redis.asyncio.connection.Connection` only has a synchronous `__del__` that
emits a `ResourceWarning`. It cannot `await` the protocol's drain/close, so
the underlying TCP socket and (for `rediss://`) the TLS session are never
released cleanly. They linger until the OS reaps them via TCP keepalive.

In production this surfaces whenever anything else still references the
orphaned client (a traceback held by a log handler, Sentry breadcrumb,
background task closure, etc.). The Python objects stay live, the sockets
stay `ESTABLISHED` on the Redis server, and the `CLIENT LIST` slot count
grows with each reconnect.

## Run

Requires a local Redis on `localhost:6379`.

```
uv run python repro.py
```

## Output (python-socketio 5.16.1, redis 5.x, Python 3.13)

```
warmup        heap={'Redis': 1, 'ConnectionPool': 1, 'Connection': 1}  sockets=1
reconnect #1  heap={'Redis': 2, 'ConnectionPool': 2, 'Connection': 2}  sockets=2  refs_held=1
reconnect #2  heap={'Redis': 3, 'ConnectionPool': 3, 'Connection': 3}  sockets=3  refs_held=2
reconnect #3  heap={'Redis': 4, 'ConnectionPool': 4, 'Connection': 4}  sockets=4  refs_held=3
reconnect #4  heap={'Redis': 5, 'ConnectionPool': 5, 'Connection': 5}  sockets=5  refs_held=4
reconnect #5  heap={'Redis': 6, 'ConnectionPool': 6, 'Connection': 6}  sockets=6  refs_held=5

release refs and gc.collect():
              heap={'Redis': 1, 'ConnectionPool': 1, 'Connection': 1}  sockets=1
```

A `ResourceWarning: unclosed Connection <redis.asyncio.connection.Connection(...)>`
is emitted for each orphaned client when it is finally GC'd.

## Versions

Reproduces on:
- python-socketio 5.16.1 (current main)
- python-socketio 5.8.0

5.15.0 (#1534) made the initial connect resilient but did not change the
reconnect path.

## Suggested fix

`_redis_connect` is sync today but its two callers (`_publish`,
`_redis_listen_with_retries`) are already async. Making the cleanup awaitable
is mechanically straightforward:

```python
async def _redis_connect(self):
    if self.pubsub is not None:
        try:
            await self.pubsub.aclose()
        except Exception:
            pass
    if self.redis is not None:
        try:
            await self.redis.aclose()
        except Exception:
            pass
    # ... existing code that builds new self.redis and self.pubsub
```
