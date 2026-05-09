"""Standalone ASGI socket.io server, AsyncRedisManager wired via the
documented public constructor:

    https://python-socketio.readthedocs.io/en/latest/server.html#using-a-message-queue

Run under gunicorn with `uvicorn.workers.UvicornH11Worker`. The manager's
listen task is spawned the first time a client connects (handled by
`AsyncServer` itself in `_handle_connect`)."""
import os

import socketio

REDIS_URL = os.environ.get("REPRO_REDIS_URL", "redis://127.0.0.1:6391/0")

mgr = socketio.AsyncRedisManager(REDIS_URL)
sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=mgr,
    cors_allowed_origins="*",
)
app = socketio.ASGIApp(sio)


@sio.event
async def connect(sid, environ):
    pass
