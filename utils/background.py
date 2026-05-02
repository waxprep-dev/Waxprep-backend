"""
Background task helper — fire‑and‑forget with error logging.
"""

import asyncio


def bg_task(coro):
    """
    Schedules a coroutine to run in the background.
    If it raises an exception, the error is printed instead of being swallowed.
    """
    task = asyncio.ensure_future(coro)

    def _handle_done(t):
        try:
            t.result()
        except Exception as e:
            print(f"Background task error: {e}")

    task.add_done_callback(_handle_done)
    return task
