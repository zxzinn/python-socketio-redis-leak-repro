"""Why server-side count doesn't grow: SETNAME runs on a borrowed connection
that is returned to the pool. Use a publish so Python actually opens the socket
and the previous client's pool keeps its connection alive."""

import asyncio

from redis.asyncio import Redis
from socketio import AsyncRedisManager


async def list_clients(probe: Redis) -> str:
    info = await probe.execute_command("CLIENT", "LIST")
    return info.decode() if isinstance(info, bytes) else info


async def count_clients(probe: Redis) -> int:
    text = await list_clients(probe)
    return text.count("\n") + (0 if text.endswith("\n") else 1)


async def main() -> None:
    probe = Redis.from_url("redis://localhost:6379/0")
    await probe.execute_command("CLIENT", "KILL", "TYPE", "normal")
    await asyncio.sleep(0.3)
    base = await count_clients(probe)
    print(f"baseline server clients: {base}")

    mgr = AsyncRedisManager("redis://localhost:6379/0", write_only=True)
    abandoned = []  # hold strong refs

    for i in range(5):
        mgr._redis_connect()
        await mgr.redis.publish("ch", b"x")  # establish actual TCP socket
        abandoned.append(mgr.redis)
        n = await count_clients(probe)
        print(f"after _redis_connect+publish #{i + 1}: server clients = {n}")

    print("\nFull CLIENT LIST:")
    print(await list_clients(probe))
    await probe.aclose()


if __name__ == "__main__":
    asyncio.run(main())
