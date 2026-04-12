# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
"""Central worker pool for managing concurrent execution.

Provides a shared thread pool that resource managers, filters, and actions
use instead of creating their own ThreadPoolExecutors. This gives callers
a single place to manage concurrency limits, and avoids the overhead of
repeatedly creating and destroying thread pools.

The primary interface is ``WorkerPool``, which owns a shared
``ThreadPoolExecutor`` and hands out ``ScopedExecutor`` instances that
honour per-operation concurrency limits while sharing the underlying
threads.

Usage::

    pool = WorkerPool(max_workers=16)

    # Use pool.executor as a drop-in for ThreadPoolExecutor
    with pool.executor(max_workers=3) as w:
        results = list(w.map(func, items))

    pool.shutdown()

For testing, ``MainThreadWorkerPool`` provides the same interface but
runs everything synchronously on the calling thread.
"""
import logging
import os
import threading

from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger('custodian.worker')

# Default ceiling for the shared thread pool.
DEFAULT_MAX_WORKERS = 16


def _resolve_max_workers(max_workers=None):
    """Determine the worker pool size.

    Priority: explicit parameter > C7N_MAX_WORKERS env var > DEFAULT_MAX_WORKERS.
    """
    if max_workers is not None:
        return int(max_workers)
    env = os.environ.get('C7N_MAX_WORKERS')
    if env is not None:
        return int(env)
    return DEFAULT_MAX_WORKERS


class ScopedExecutor:
    """An executor scoped to a single operation.

    Limits the number of concurrently outstanding tasks from this scope
    using a ``threading.Semaphore``, while delegating actual execution to
    a shared ``WorkerPool``.  This means the caller gets the familiar
    ``with executor(max_workers=N) as w:`` pattern, but threads are
    reused across operations.
    """

    def __init__(self, pool, max_workers):
        self._pool = pool
        self._max_workers = max_workers
        self._semaphore = threading.Semaphore(max_workers)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, fn, *args, **kwargs):
        self._semaphore.acquire()
        try:
            future = self._pool._pool.submit(fn, *args, **kwargs)
        except Exception:
            self._semaphore.release()
            raise
        future.add_done_callback(lambda _f: self._semaphore.release())
        return future

    def map(self, fn, *iterables, timeout=None, chunksize=1):
        """Map *fn* over *iterables*, honouring the concurrency limit.

        Unlike ``ThreadPoolExecutor.map`` this implementation is built on
        ``submit`` so that the semaphore naturally back-pressures the
        caller.  Results are yielded in the original order.
        """
        fs = [self.submit(fn, *a) for a in zip(*iterables)]
        try:
            for future in fs:
                yield future.result(timeout=timeout)
        finally:
            for future in fs:
                future.cancel()


class WorkerPool:
    """Central shared thread pool.

    A single ``WorkerPool`` is meant to live for the duration of a policy
    execution (owned by ``ExecutionContext``).  All resource managers,
    filters, and actions obtain executors from the pool via
    ``pool.executor(max_workers=N)``.

    The pool lazily creates the underlying ``ThreadPoolExecutor`` on first
    use so that no threads are spawned if a policy never needs them.
    """

    def __init__(self, max_workers=None):
        self.max_workers = _resolve_max_workers(max_workers)
        self._pool = None
        self._lock = threading.Lock()

    def _ensure_pool(self):
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    self._pool = ThreadPoolExecutor(
                        max_workers=self.max_workers
                    )

    def executor(self, max_workers=3):
        """Return a ``ScopedExecutor`` backed by the shared pool.

        *max_workers* caps concurrently outstanding tasks for the
        returned executor.  The shared pool's own ``max_workers`` caps
        total thread-level concurrency across all scoped executors.
        """
        self._ensure_pool()
        return ScopedExecutor(self, max_workers)

    def shutdown(self, wait=True):
        """Shut down the underlying thread pool, if it was created."""
        if self._pool is not None:
            self._pool.shutdown(wait=wait)
            self._pool = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()
        return False


class MainThreadWorkerPool:
    """A synchronous worker pool for testing.

    Drop-in replacement for ``WorkerPool`` that runs every task on the
    calling thread via ``MainThreadExecutor``.
    """

    def __init__(self, max_workers=None):
        self.max_workers = max_workers or DEFAULT_MAX_WORKERS

    def executor(self, max_workers=3):
        # Lazy import to avoid circular dependency with c7n.executor.
        from c7n.executor import MainThreadExecutor
        return MainThreadExecutor(max_workers=max_workers)

    def shutdown(self, wait=True):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
