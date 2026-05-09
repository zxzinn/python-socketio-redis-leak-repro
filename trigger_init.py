"""Connect a socket.io client to each gunicorn worker so the server
calls `manager.initialize()` and spawns its background listen task on
that worker's event loop. Disconnect after a short pause; the manager
keeps running."""
import asyncio
import sys

import socketio


async def connect_one(url: str) -> None:
    client = socketio.AsyncClient(reconnection=False)
    try:
        await client.connect(url)
        await asyncio.sleep(0.5)
        await client.disconnect()
    except Exception as e:
        print(f"connect to {url} failed: {type(e).__name__}: {e}", file=sys.stderr)


async def main(url: str, n: int) -> None:
    # Open n separate client sessions in parallel so gunicorn's load
    # balancing routes them across all workers (each one triggers
    # manager.initialize() on its own worker).
    await asyncio.gather(*[connect_one(url) for _ in range(n)])


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    asyncio.run(main(url, n))
