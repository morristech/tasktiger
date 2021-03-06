"""Test workers."""

import datetime
from multiprocessing import Process
import time

from freezefrog import FreezeTime

from tasktiger import Task, Worker

from .config import DELAY
from .tasks import long_task_killed, long_task_ok
from .test_base import BaseTestCase
from .utils import external_worker


class TestMaxWorkers(BaseTestCase):
    """Single Worker Queue tests."""

    def test_max_workers(self):
        """Test Single Worker Queue."""

        # Queue three tasks
        for i in range(0, 3):
            task = Task(self.tiger, long_task_killed, queue='a')
            task.delay()
        self._ensure_queues(queued={'a': 3})

        # Start two workers and wait until they start processing.
        worker1 = Process(target=external_worker,
                          kwargs={'max_workers_per_queue': 2})
        worker2 = Process(target=external_worker,
                          kwargs={'max_workers_per_queue': 2})
        worker1.start()
        worker2.start()
        time.sleep(DELAY)

        # This worker should fail to get the queue lock and exit immediately
        worker = Worker(self.tiger)
        worker.max_workers_per_queue = 2
        worker.run(once=True, force_once=True)
        self._ensure_queues(active={'a': 2}, queued={'a': 1})
        # Wait for external workers
        worker1.join()
        worker2.join()


    def test_single_worker_queue(self):
        """
        Test Single Worker Queue.

        Single worker queues are the same as running with MAX_WORKERS_PER_QUEUE
        set to 1.
        """

        # Queue two tasks
        task = Task(self.tiger, long_task_ok, queue='swq')
        task.delay()
        task = Task(self.tiger, long_task_ok, queue='swq')
        task.delay()
        self._ensure_queues(queued={'swq': 2})

        # Start a worker and wait until it starts processing.
        # It should start processing one task and hold a lock on the queue
        worker = Process(target=external_worker)
        worker.start()

        # Wait up to 2 seconds for external task to start
        result = self.conn.blpop('long_task_ok', 2)
        assert result[1] == '1'

        # This worker should fail to get the queue lock and exit immediately
        Worker(self.tiger).run(once=True, force_once=True)
        self._ensure_queues(active={'swq': 1}, queued={'swq': 1})
        # Wait for external worker
        worker.join()

        # Retest using a non-single worker queue
        # Queue two tasks
        task = Task(self.tiger, long_task_ok, queue='not_swq')
        task.delay()
        task = Task(self.tiger, long_task_ok, queue='not_swq')
        task.delay()
        self._ensure_queues(queued={'not_swq': 2})

        # Start a worker and wait until it starts processing.
        # It should start processing one task
        worker = Process(target=external_worker)
        worker.start()
        time.sleep(DELAY)

        # This worker should process the second task
        Worker(self.tiger).run(once=True, force_once=True)

        # Queues should be empty
        self._ensure_queues()

        worker.join()

    def test_queue_system_lock(self):
        """Test queue system lock."""

        with FreezeTime(datetime.datetime(2014, 1, 1)):
            # Queue three tasks
            for i in range(0, 3):
                task = Task(self.tiger, long_task_ok, queue='a')
                task.delay()
            self._ensure_queues(queued={'a': 3})

            # Ensure we can process one
            worker = Worker(self.tiger)
            worker.max_workers_per_queue = 2
            worker.run(once=True, force_once=True)
            self._ensure_queues(queued={'a': 2})

            # Set system lock so no processing should occur for 10 seconds
            self.tiger.set_queue_system_lock('a', 10)

            lock_timeout = self.tiger.get_queue_system_lock('a')
            assert lock_timeout == time.time() + 10

        # Confirm tasks don't get processed within the system lock timeout
        with FreezeTime(datetime.datetime(2014, 1, 1, 0, 0, 9)):
            worker = Worker(self.tiger)
            worker.max_workers_per_queue = 2
            worker.run(once=True, force_once=True)
            self._ensure_queues(queued={'a': 2})

        # 10 seconds in the future the lock should have expired
        with FreezeTime(datetime.datetime(2014, 1, 1, 0, 0, 10)):
            worker = Worker(self.tiger)
            worker.max_workers_per_queue = 2
            worker.run(once=True, force_once=True)
            self._ensure_queues(queued={'a': 1})
