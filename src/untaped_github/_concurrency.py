"""Bounded concurrency helpers shared by local corpus use cases."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed


def bounded_map[ItemT, ResultT](
    fn: Callable[[ItemT], ResultT],
    items: Sequence[ItemT],
    *,
    concurrency: int,
    on_each: Callable[[ItemT, ResultT], None],
) -> None:
    """Apply ``fn`` to every item with at most ``concurrency`` worker threads."""
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if len(items) <= 1 or concurrency == 1:
        for item in items:
            on_each(item, fn(item))
        return
    with ThreadPoolExecutor(max_workers=min(concurrency, len(items))) as executor:
        try:
            futures = {executor.submit(fn, item): item for item in items}
            for future in as_completed(futures):
                on_each(futures[future], future.result())
        except BaseException:
            executor.shutdown(cancel_futures=True)
            raise
