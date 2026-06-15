"""Keep-alive HTTP-сервер для безкоштовного Render (щоб сервіс не засинав).

Працює в тому ж event loop, що й бот (aiohttp уже є залежністю aiogram).
"""
from aiohttp import web


async def _ping(_request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def start_web(port: int) -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", _ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner
