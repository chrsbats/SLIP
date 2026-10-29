"""One Runner-owned async I/O worker, returning native pollable Futures."""

import asyncio
import inspect
from concurrent.futures import Future
from threading import Lock, Thread, current_thread

import httpx


class IOWorker:
    def __init__(self):
        self.closed = False
        self.error = None
        self.loop = None
        self.lock = Lock()
        self.ready = Future()
        self.thread = Thread(target=self.run, name="slip-io", daemon=True)
        self.thread.start()
        try:
            self.ready.result()
        except BaseException:
            self.thread.join()
            raise

    def run(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.serve())
        except BaseException as error:
            self.error = error
            if not self.ready.done():
                self.ready.set_exception(error)
        finally:
            if self.loop is not None:
                try:
                    self.loop.run_until_complete(
                        self.loop.shutdown_asyncgens(),
                    )
                    self.loop.run_until_complete(
                        self.loop.shutdown_default_executor(),
                    )
                finally:
                    self.loop.close()

    async def serve(self):
        self.slots = asyncio.Semaphore(32)
        self.stopping = asyncio.Event()
        async with httpx.AsyncClient(
            follow_redirects=True, limits=httpx.Limits(max_connections=32),
        ) as self.client:
            self.ready.set_result(None)
            try:
                await self.stopping.wait()
            finally:
                pending = asyncio.all_tasks() - {asyncio.current_task()}
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

    def submit(self, function, *args):
        self.check_host_thread()
        if not (inspect.iscoroutinefunction(function)
                or inspect.iscoroutinefunction(
                    getattr(function, "__call__", None),
                )):
            raise TypeError(
                "I/O jobs require a native async function; "
                "SLIP tasks are deferred",
            )
        with self.lock:
            if self.closed:
                raise RuntimeError("I/O worker is closed")
            return asyncio.run_coroutine_threadsafe(
                self.call(function, args), self.loop,
            )

    async def call(self, function, args):
        async with self.slots:
            return await function(*args)

    def check_host_thread(self):
        if current_thread() is self.thread:
            raise RuntimeError("This operation belongs to the host thread")

    def close(self):
        self.check_host_thread()
        with self.lock:
            if not self.closed:
                self.closed = True
                self.loop.call_soon_threadsafe(self.stopping.set)
        self.thread.join()
        if self.error is not None:
            raise self.error


def job_result(job):
    if not job.done():
        raise TimeoutError("I/O job is not complete")
    if not job.cancelled():
        error = job.exception()
        if error is not None:
            error.slip_trace = []
    return job.result()
