import logging
import json
from time import sleep
from queue import Queue, Empty
from threading import Thread
from models import TaskDB
from task import Task
from constants import QUEUING, RUNNING
from appSettings import app_settings
log = logging.getLogger(__name__)

class Worker(Thread):

    def __init__(self):
        super().__init__(daemon=True)
        self.queue = Queue()
        self.active = False
        self.closed = False
        self.start()

    def run(self):
        while not self.closed:
            try:
                func = self.queue.get(timeout=1)
            except Empty:
                continue
            self.active = True
            func()
            self.active = False
        self.active = False

    def submit(self, func):
        self.queue.put(func)

    def stop(self):
        self.closed = True

class WorkerManager(Thread):
    __doc__ = 'docstring for WorkerManager'

    def __init__(self, task_mgr):
        super().__init__(daemon=True)
        self.task_mgr = task_mgr
        task_mgr.setWorkerMgr(self)
        self.workers = []
        self.closed = False

    def spawn_worker(self):
        w = Worker()
        self.workers.append(w)

    def adjust_worker_count(self):
        worker_count = len(self.workers)
        if worker_count < app_settings.active_downloads:
            self.spawn_worker()
            return
        if worker_count > app_settings.active_downloads:
            for w in self.workers:
                if not w.active:
                    w.stop()
                    self.workers.remove(w)
                    return

    def fetchTask(self):
        task_data = TaskDB.getTaskByStatus(QUEUING)
        if task_data and task_data.id not in self.task_mgr.tasks_activating:
            task = Task(task_data.id, task_data.url, task_data.path, json.loads(task_data.headers), task_data.quality, app_settings.connections)
            return task

    def find_worker_free(self):
        for w in self.workers:
            if not w.active:
                return w

    def assign_task_for_worker(self, task):
        for w in self.workers:
            if not w.active:
                w.submit(task.run)
                return True
        return False

    def run(self):
        while not self.closed:
            self.adjust_worker_count()
            w = self.find_worker_free()
            if w:
                task = None
                try:
                    task = self.fetchTask()
                except Exception as err:
                    log.error('fetch task error %s', err)
                    continue
                if task:
                    w.submit(task.run)
                    self.task_mgr.register(task)
                else:
                    sleep(5)
            else:
                sleep(5)

    def force_run_task(self, task_data):
        task = Task(task_data.id, task_data.url, task_data.path, json.loads(task_data.headers), task_data.quality, app_settings.connections)
        self.spawn_worker()
        self.task_mgr.register(task)
        self.assign_task_for_worker(task)

    def load_task_unfinished(self):
        tasks_data = TaskDB.getAllTasksByStatus(RUNNING)
        for task_data in tasks_data:
            self.force_run_task(task_data)

    def shutdown(self):
        self.closed = True
        for t in self.workers:
            t.stop()

