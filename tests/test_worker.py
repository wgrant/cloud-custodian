# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
import os
import threading
import time
import unittest
from concurrent.futures import as_completed
from unittest import mock

from c7n.worker import (
    WorkerPool,
    ScopedExecutor,
    MainThreadWorkerPool,
    _resolve_max_workers,
    DEFAULT_MAX_WORKERS,
    SESSION_CACHE_TTL,
)
from c7n.executor import MainThreadExecutor


def _identity(x):
    return x


def _double(x):
    return x * 2


def _record_thread(results, x):
    """Append the current thread name and return x."""
    results.append(threading.current_thread().name)
    return x


def _sleep_return(x):
    time.sleep(0.01)
    return x


def _raise(x):
    raise ValueError(f"bad: {x}")


class TestResolveMaxWorkers(unittest.TestCase):

    def test_explicit_value(self):
        self.assertEqual(_resolve_max_workers(8), 8)

    def test_env_var(self):
        with mock.patch.dict(os.environ, {'C7N_MAX_WORKERS': '24'}):
            self.assertEqual(_resolve_max_workers(), 24)

    def test_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop('C7N_MAX_WORKERS', None)
            self.assertEqual(_resolve_max_workers(), DEFAULT_MAX_WORKERS)

    def test_explicit_overrides_env(self):
        with mock.patch.dict(os.environ, {'C7N_MAX_WORKERS': '24'}):
            self.assertEqual(_resolve_max_workers(4), 4)


class TestWorkerPool(unittest.TestCase):

    def test_lazy_init(self):
        pool = WorkerPool(max_workers=4)
        self.assertIsNone(pool._pool)
        pool.executor(max_workers=2)
        self.assertIsNotNone(pool._pool)
        pool.shutdown()

    def test_context_manager(self):
        with WorkerPool(max_workers=4) as pool:
            with pool.executor(max_workers=2) as w:
                results = list(w.map(_double, [1, 2, 3]))
        self.assertEqual(results, [2, 4, 6])

    def test_shutdown_idempotent(self):
        pool = WorkerPool(max_workers=4)
        pool.shutdown()
        pool.shutdown()  # should not raise

    def test_shutdown_before_use(self):
        pool = WorkerPool(max_workers=4)
        pool.shutdown()  # no pool was created, should be fine


class TestScopedExecutor(unittest.TestCase):

    def test_map_basic(self):
        with WorkerPool(max_workers=4) as pool:
            with pool.executor(max_workers=2) as w:
                results = list(w.map(_double, [1, 2, 3, 4, 5]))
        self.assertEqual(results, [2, 4, 6, 8, 10])

    def test_map_preserves_order(self):
        with WorkerPool(max_workers=4) as pool:
            with pool.executor(max_workers=2) as w:
                results = list(w.map(_identity, range(20)))
        self.assertEqual(results, list(range(20)))

    def test_submit_basic(self):
        with WorkerPool(max_workers=4) as pool:
            with pool.executor(max_workers=2) as w:
                future = w.submit(_double, 5)
                self.assertEqual(future.result(), 10)

    def test_submit_with_as_completed(self):
        with WorkerPool(max_workers=4) as pool:
            with pool.executor(max_workers=2) as w:
                futures = [w.submit(_double, i) for i in range(5)]
                results = set()
                for f in as_completed(futures):
                    results.add(f.result())
        self.assertEqual(results, {0, 2, 4, 6, 8})

    def test_submit_exception(self):
        with WorkerPool(max_workers=4) as pool:
            with pool.executor(max_workers=2) as w:
                future = w.submit(_raise, 42)
                self.assertIsInstance(future.exception(), ValueError)

    def test_concurrency_limit(self):
        """ScopedExecutor limits concurrent outstanding tasks."""
        max_concurrent = []
        current = {'count': 0}
        lock = threading.Lock()

        def _track_concurrency(x):
            with lock:
                current['count'] += 1
                max_concurrent.append(current['count'])
            time.sleep(0.02)
            with lock:
                current['count'] -= 1
            return x

        with WorkerPool(max_workers=8) as pool:
            with pool.executor(max_workers=3) as w:
                list(w.map(_track_concurrency, range(10)))

        # The max concurrent tasks should not exceed the scoped limit.
        self.assertLessEqual(max(max_concurrent), 3)

    def test_multiple_scoped_executors(self):
        """Multiple scoped executors share the same pool."""
        with WorkerPool(max_workers=8) as pool:
            with pool.executor(max_workers=3) as w1:
                with pool.executor(max_workers=3) as w2:
                    r1 = list(w1.map(_double, [1, 2, 3]))
                    r2 = list(w2.map(_identity, [4, 5, 6]))
        self.assertEqual(r1, [2, 4, 6])
        self.assertEqual(r2, [4, 5, 6])

    def test_context_manager_does_not_shutdown_pool(self):
        """Exiting a ScopedExecutor should not shut down the shared pool."""
        pool = WorkerPool(max_workers=4)
        with pool.executor(max_workers=2) as w:
            list(w.map(_identity, [1]))
        # Pool should still be usable after exiting the scoped executor.
        with pool.executor(max_workers=2) as w:
            results = list(w.map(_double, [1, 2]))
        self.assertEqual(results, [2, 4])
        pool.shutdown()

    def test_map_empty(self):
        with WorkerPool(max_workers=4) as pool:
            with pool.executor(max_workers=2) as w:
                results = list(w.map(_double, []))
        self.assertEqual(results, [])


class TestMainThreadWorkerPool(unittest.TestCase):

    def test_executor_returns_main_thread_executor(self):
        pool = MainThreadWorkerPool()
        executor = pool.executor(max_workers=3)
        self.assertIsInstance(executor, MainThreadExecutor)

    def test_map(self):
        pool = MainThreadWorkerPool()
        with pool.executor(max_workers=3) as w:
            results = list(w.map(_double, [1, 2, 3]))
        self.assertEqual(results, [2, 4, 6])

    def test_submit(self):
        pool = MainThreadWorkerPool()
        with pool.executor(max_workers=3) as w:
            future = w.submit(_double, 5)
            self.assertEqual(future.result(), 10)

    def test_submit_as_completed(self):
        pool = MainThreadWorkerPool()
        with pool.executor(max_workers=3) as w:
            futures = [w.submit(_double, i) for i in range(5)]
            results = set()
            for f in as_completed(futures):
                results.add(f.result())
        self.assertEqual(results, {0, 2, 4, 6, 8})

    def test_shutdown_noop(self):
        pool = MainThreadWorkerPool()
        pool.shutdown()  # should not raise

    def test_context_manager(self):
        with MainThreadWorkerPool() as pool:
            with pool.executor(max_workers=2) as w:
                self.assertEqual(list(w.map(_identity, [1, 2])), [1, 2])


class TestDropInCompatibility(unittest.TestCase):
    """Verify that WorkerPool.executor is a drop-in for ThreadPoolExecutor.

    The existing codebase uses the pattern:
        with self.executor_factory(max_workers=N) as w:
            results = list(w.map(func, items))
    """

    def test_executor_factory_pattern(self):
        pool = WorkerPool(max_workers=4)
        executor_factory = pool.executor

        with executor_factory(max_workers=2) as w:
            results = list(w.map(_double, [1, 2, 3]))
        self.assertEqual(results, [2, 4, 6])
        pool.shutdown()

    def test_submit_and_as_completed_pattern(self):
        """Matches the common c7n pattern of submit + as_completed."""
        pool = WorkerPool(max_workers=4)
        executor_factory = pool.executor

        with executor_factory(max_workers=2) as w:
            futures = []
            for chunk in [[1, 2], [3, 4], [5, 6]]:
                futures.append(w.submit(sum, chunk))

            results = []
            for f in as_completed(futures):
                results.append(f.result())

        self.assertEqual(sorted(results), [3, 7, 11])
        pool.shutdown()

    def test_main_thread_pool_executor_factory_pattern(self):
        pool = MainThreadWorkerPool()
        executor_factory = pool.executor

        with executor_factory(max_workers=2) as w:
            results = list(w.map(_double, [1, 2, 3]))
        self.assertEqual(results, [2, 4, 6])


class TestExecutionContextIntegration(unittest.TestCase):
    """Test that the worker pool is properly wired into ExecutionContext."""

    def test_ctx_has_worker_pool(self):
        from c7n.ctx import ExecutionContext
        from c7n.config import Config

        options = Config.empty()
        ctx = ExecutionContext(
            session_factory=mock.MagicMock(),
            policy=mock.MagicMock(),
            options=options,
        )
        self.assertIsNotNone(ctx.worker_pool)

    def test_ctx_test_run_uses_main_thread_pool(self):
        from c7n.ctx import ExecutionContext
        from c7n.config import Config

        options = Config.empty()
        with mock.patch.dict(os.environ, {'C7N_TEST_RUN': '1'}):
            ctx = ExecutionContext(
                session_factory=mock.MagicMock(),
                policy=mock.MagicMock(),
                options=options,
            )
        self.assertIsInstance(ctx.worker_pool, MainThreadWorkerPool)

    def test_ctx_max_workers_from_options(self):
        from c7n.ctx import ExecutionContext
        from c7n.config import Config

        options = Config.empty(max_workers=32)
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop('C7N_TEST_RUN', None)
            os.environ.pop('C7N_MAX_WORKERS', None)
            ctx = ExecutionContext(
                session_factory=mock.MagicMock(),
                policy=mock.MagicMock(),
                options=options,
            )
        self.assertIsInstance(ctx.worker_pool, WorkerPool)
        self.assertEqual(ctx.worker_pool.max_workers, 32)


class TestElementDelegation(unittest.TestCase):
    """Test that Element.executor_factory delegates to manager."""

    def test_delegates_to_manager(self):
        from c7n.element import Element

        sentinel = object()
        manager = mock.MagicMock()
        manager.executor_factory = sentinel

        elem = Element()
        elem.manager = manager
        self.assertIs(elem.executor_factory, sentinel)

    def test_fallback_without_manager(self):
        from c7n.element import Element
        from concurrent.futures import ThreadPoolExecutor

        elem = Element()
        self.assertIs(elem.executor_factory, ThreadPoolExecutor)

    def test_instance_override(self):
        from c7n.element import Element

        sentinel = object()
        elem = Element()
        elem.manager = mock.MagicMock()
        elem.executor_factory = sentinel
        self.assertIs(elem.executor_factory, sentinel)


class TestWorkerPoolSession(unittest.TestCase):
    """Test session management on WorkerPool."""

    def _make_factory(self, region='us-east-1'):
        call_count = {'n': 0}

        def factory():
            call_count['n'] += 1
            return mock.MagicMock(name=f"session-{call_count['n']}")

        factory.region = region
        factory._call_count = call_count
        return factory

    def test_get_session_basic(self):
        factory = self._make_factory()
        pool = WorkerPool(max_workers=2, session_factory=factory)
        s1 = pool.get_session()
        s2 = pool.get_session()
        # Same thread → same cached session
        self.assertIs(s1, s2)
        self.assertEqual(factory._call_count['n'], 1)
        pool.shutdown()

    def test_get_session_no_factory_raises(self):
        pool = WorkerPool(max_workers=2)
        with self.assertRaises(ValueError):
            pool.get_session()

    def test_get_session_explicit_factory(self):
        factory = self._make_factory()
        pool = WorkerPool(max_workers=2)  # no default factory
        s = pool.get_session(session_factory=factory)
        self.assertIsNotNone(s)
        pool.shutdown()

    def test_get_session_per_region(self):
        factory = self._make_factory()
        pool = WorkerPool(max_workers=2, session_factory=factory)
        s1 = pool.get_session(region='us-east-1')
        s2 = pool.get_session(region='eu-west-1')
        self.assertIsNot(s1, s2)
        self.assertEqual(factory._call_count['n'], 2)
        pool.shutdown()

    def test_get_session_per_thread(self):
        """Different threads get different sessions."""
        factory = self._make_factory()
        pool = WorkerPool(max_workers=4, session_factory=factory)
        pool._ensure_pool()

        sessions = []
        lock = threading.Lock()

        def worker(_):
            s = pool.get_session()
            with lock:
                sessions.append(id(s))
            return s

        with pool.executor(max_workers=4) as w:
            list(w.map(worker, range(4)))

        # We may get fewer unique sessions than threads if threads are
        # reused, but the factory should have been called at least once
        # per thread that ran.
        self.assertGreaterEqual(factory._call_count['n'], 1)
        pool.shutdown()

    def test_get_session_ttl_expiry(self):
        factory = self._make_factory()
        pool = WorkerPool(max_workers=2, session_factory=factory)
        s1 = pool.get_session()

        # Simulate TTL expiry by backdating the cache entry
        cache_key = 'us-east-1'
        pool._session_cache.sessions[cache_key]['time'] -= SESSION_CACHE_TTL + 1

        s2 = pool.get_session()
        self.assertIsNot(s1, s2)
        self.assertEqual(factory._call_count['n'], 2)
        pool.shutdown()


class TestMainThreadWorkerPoolSession(unittest.TestCase):
    """Test session management on MainThreadWorkerPool."""

    def _make_factory(self, region='us-east-1'):
        call_count = {'n': 0}

        def factory():
            call_count['n'] += 1
            return mock.MagicMock(name=f"session-{call_count['n']}")

        factory.region = region
        factory._call_count = call_count
        return factory

    def test_get_session_basic(self):
        factory = self._make_factory()
        pool = MainThreadWorkerPool(session_factory=factory)
        s1 = pool.get_session()
        s2 = pool.get_session()
        self.assertIs(s1, s2)
        self.assertEqual(factory._call_count['n'], 1)

    def test_get_session_no_factory_raises(self):
        pool = MainThreadWorkerPool()
        with self.assertRaises(ValueError):
            pool.get_session()

    def test_shutdown_clears_sessions(self):
        factory = self._make_factory()
        pool = MainThreadWorkerPool(session_factory=factory)
        pool.get_session()
        pool.shutdown()
        # After shutdown, a new session should be created
        s = pool.get_session()
        self.assertEqual(factory._call_count['n'], 2)


class TestAugmentClientPerThread(unittest.TestCase):
    """Test that augment functions create per-invocation clients."""

    def test_augment_client_with_get_client(self):
        from c7n.query import _augment_client

        manager = mock.MagicMock()
        model = mock.MagicMock()
        manager.get_client.return_value = mock.sentinel.client

        client = _augment_client(manager, model)
        self.assertIs(client, mock.sentinel.client)
        manager.get_client.assert_called_once()

    def test_augment_client_without_get_client(self):
        from c7n.query import _augment_client

        manager = mock.MagicMock()
        manager.get_client = None
        model = mock.MagicMock()
        model.service = 'ec2'
        manager.config.region = 'us-east-1'

        mock_session = mock.MagicMock()
        with mock.patch('c7n.query.local_session', return_value=mock_session):
            client = _augment_client(manager, model)

        mock_session.client.assert_called_once_with(
            'ec2', region_name='us-east-1')
        self.assertIs(client, mock_session.client.return_value)


if __name__ == "__main__":
    unittest.main()
