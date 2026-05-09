"""Standalone ASGI app: socketio.AsyncServer + AsyncRedisManager via the
documented public constructor. Designed to be run under gunicorn
UvicornH11Worker so that manager.initialize() spawns its background
listen task on the worker's event loop.

Mirrors the prod wiring at miguelgrinberg/python-socketio's example."""
import os
import socketio

REDIS_URL = os.environ.get("REPRO_REDIS_URL", "redis://127.0.0.1:6391/0")

mgr = socketio.AsyncRedisManager(REDIS_URL)
sio = socketio.AsyncServer(async_mode="asgi", client_manager=mgr)
inner = socketio.ASGIApp(sio)


async def app(scope, receive, send):
    """Wrap the socketio ASGI app so the lifespan event triggers
    manager.initialize() (which would otherwise be deferred until the
    first socket.io request)."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                if not sio.manager_initialized:
                    sio.manager_initialized = True
                    sio.manager.set_server(sio)
                    sio.manager.initialize()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    else:
        await inner(scope, receive, send)
