"""TCP proxy listening on 6391, forwarding to real Redis on 6379.
On SIGUSR1, sends invalid RESP bytes to all client writers. redis-py's
parser raises RedisError but the TCP socket stays alive on both sides.

This simulates a Redis-side hiccup that produces a RedisError on the
client without an actual server-side close. It's the cleanest way to
trigger AsyncRedisManager._redis_listen_with_retries' except branch
from outside the process, using only public-facing TCP semantics."""
import asyncio
import os
import signal


CONNS: list[tuple[asyncio.StreamWriter, asyncio.StreamWriter]] = []


async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(4096)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except Exception:
        pass


async def handle(client_reader, client_writer):
    try:
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", 6379)
    except Exception:
        client_writer.close()
        return
    CONNS.append((client_writer, up_writer))
    try:
        await asyncio.gather(
            pipe(client_reader, up_writer),
            pipe(up_reader, client_writer),
        )
    finally:
        for w in (client_writer, up_writer):
            try:
                w.close()
            except Exception:
                pass


def send_garbage(*_):
    print(f"[proxy] sending garbage to {len(CONNS)} clients", flush=True)
    for cw, _uw in list(CONNS):
        try:
            cw.write(b"-ERR fake bogus garbage line\r\nGARBAGE_NOT_RESP\xff\xff\r\n" * 10)
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", 6391)
    print(f"[proxy] 6391 -> 6379, pid={os.getpid()}", flush=True)
    print(f"[proxy] kill -USR1 {os.getpid()} sends garbage", flush=True)
    asyncio.get_running_loop().add_signal_handler(signal.SIGUSR1, send_garbage)
    async with server:
        await server.serve_forever()


asyncio.run(main())
