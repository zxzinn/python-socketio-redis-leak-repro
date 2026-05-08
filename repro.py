"""Reproduce the AsyncRedisManager reconnect resource leak.

`AsyncRedisManager._redis_connect` overwrites self.redis and self.pubsub with
fresh instances without closing the previous ones. The Connection class only
has a sync __del__ that emits a ResourceWarning, so the underlying socket and
SSL session are never awaited closed.

In production this surfaces as a TCP socket / server-side CLIENT slot leak
whenever anything holds a reference to the orphaned client (a traceback held
by a log handler, Sentry breadcrumb, background task, etc.).

To make the leak observable we keep an explicit reference to every orphaned
client so it cannot be GC'd, then count Redis Python objects and TCP sockets.

Usage:
    python repro.py [--reconnects N]
"""

import argparse
import asyncio
import gc
import warnings

import psutil
from redis.asyncio.client import Redis
from redis.asyncio.connection import Connection, ConnectionPool
from socketio import AsyncRedisManager


def heap_counts() -> dict[str, int]:
    gc.collect()
    counts: dict[str, int] = {}
    for obj in gc.get_objects():
        cls = type(obj)
        if cls in (Redis, ConnectionPool, Connection):
            counts[cls.__name__] = counts.get(cls.__name__, 0) + 1
    return counts


def my_sockets_to(port: int) -> int:
    me = psutil.Process()
    return sum(
        1
        for c in me.net_connections(kind="tcp")
        if c.raddr and c.raddr.port == port and c.status == "ESTABLISHED"
    )


async def main(reconnects: int) -> None:
    warnings.simplefilter("always", ResourceWarning)

    mgr = AsyncRedisManager("redis://localhost:6379/0", write_only=True)
    mgr._redis_connect()
    await mgr.redis.publish("warmup", b"x")
    print(f"warmup        heap={heap_counts()}  sockets={my_sockets_to(6379)}")

    abandoned = []
    for i in range(1, reconnects + 1):
        abandoned.append(mgr.redis)
        mgr._redis_connect()
        await mgr.redis.publish("repro", b"x")
        print(f"reconnect #{i}  heap={heap_counts()}  sockets={my_sockets_to(6379)}  refs_held={len(abandoned)}")

    print("\nrelease refs and gc.collect():")
    abandoned.clear()
    gc.collect()
    await asyncio.sleep(0.5)
    print(f"              heap={heap_counts()}  sockets={my_sockets_to(6379)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconnects", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(args.reconnects))
