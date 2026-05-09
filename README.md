# python-socketio AsyncRedisManager listen-path leak repro

For https://github.com/miguelgrinberg/python-socketio/issues/1569

## Run

```
./run.sh
```

Needs Redis on `127.0.0.1:6379` and `uv`.

## Output

```
initial server-side subscribe count: 2
after garbage #1: subscribe=4
after garbage #2: subscribe=6
...
after garbage #10: subscribe=22
```

2 workers, +2 each round. 22 final rows, all `idle == age`.

## Layout

- `app.py` ASGI socket.io server with one `AsyncRedisManager`
- `proxy.py` tcp proxy 6391 → 6379; on `SIGUSR1` writes invalid RESP
- `trigger_init.py` opens socket.io clients so each worker initializes
- `run.sh` ties it together

## Versions

python-socketio 5.8.0 and 5.16.1, redis 5.x, Python 3.13.
