# python-socketio AsyncRedisManager reconnect leak repro

Minimal reproduction for https://github.com/miguelgrinberg/python-socketio/issues/1569.

## The bug

`AsyncRedisManager._redis_connect` overwrites `self.redis` and `self.pubsub` without closing the previous ones. The old `Redis` client is never `await`ed closed, so its TCP socket (and TLS session for `rediss://`) is leaked.

`redis.asyncio.Redis` requires `await aclose()` for cleanup; its `__del__` only emits `ResourceWarning: Unclosed client session` because async cleanup cannot run in `__del__`. The manager owns the client, so the manager must close it.

`_redis_connect` runs on every reconnect:

- `_publish` calls it after a failed publish
- `_redis_listen_with_retries` calls it after any `RedisError`

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

Each iteration emits `ResourceWarning: unclosed Connection`.

Also reproduces on python-socketio 5.8.0.

## Suggested fix

`_redis_connect` is sync today but both callers are already async, so cleanup can be awaited:

```python
async def _redis_connect(self):
    if self.pubsub is not None:
        await self.pubsub.aclose()
    if self.redis is not None:
        await self.redis.aclose()
    # ... existing code that builds new self.redis and self.pubsub
```
