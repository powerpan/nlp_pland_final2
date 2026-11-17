"""Web server for PlanD: the HTTP/WebSocket API and the browser UI (Bot Mode).

`create_app()` lives in `pland.server.app`; it is imported lazily by `pland serve` so the CLI does
not pay for FastAPI unless the server is started.
"""
