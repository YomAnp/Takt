import asyncio


def new_event_loop() -> asyncio.AbstractEventLoop:
    """Psycopg requires a selector loop on Windows."""
    return asyncio.SelectorEventLoop()
