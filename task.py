import os
import json
import logging
from threading import Lock
from models import TaskDB
from exceptions import TaskWasExisted, TaskListWasExisted, TaskNotExist
from constants import QUEUING, RUNNING, STOPPED, COMPLETED, ERROR
from appSettings import app_settings
from utils import longPath, cleanName, sanitizePath, mkdirs
from StreamDownloader import StreamDownloader
log = logging.getLogger(__name__)

class TaskBase(object):

    def __init__(self, tid):
        self.id = tid
        self._status = QUEUING
        self._status_lock = Lock()
        self._call_updated_lock = Lock()
        self._subscribers = set()
        self.error = ''
        self.error_detail = ''

    def register(self, who):
        self._subscribers.add(who)

    def unregister(self, who):
        self._subscribers.remove(who)

    def fire(self):
        with self._call_updated_lock:
            subscribers = self._subscribers.copy()
            for subscriber in subscribers:
                try:
                    subscriber.update(self)
                except Exception as err:
                    log.warning('Call subscriber error %s', err)

    def status(self):
        with self._status_lock:
            return self._status

    def setStatus(self, status):
        with self._status_lock:
            self._status = status
        self.fire()

    def isRunning(self):
        return self.status() == RUNNING

    def run(self):
        try:
            if self.status() == STOPPED or self.isRunning():
                return
            self.setStatus(RUNNING)
            self._run()
            if self.status() == RUNNING:
                self.setStatus(COMPLETED)
        except Exception as err:
            self.error = str(err)
            self.setStatus(ERROR)

    def stop(self):
        if self.status() in [COMPLETED, ERROR]:
            return
        self.setStatus(STOPPED)

    def _run(self):
        raise NotImplementedError

class Task(TaskBase):
    __doc__ = 'docstring for Task'

    def __init__(self, tid, url, path, headers, quality, threads, override_file=False):
        super().__init__(tid)
        self.url = url
        self.headers = headers
        self.quality = quality
        self.override_file = override_file
        self.qualities = '[]'
        self.reset()
        self.streamdown = StreamDownloader(url, path, headers, quality, threads, reporter=self.onProgress)
        self.closed = False

    def reset(self):
        self.speed = ''
        self.eta = ''
        self.percent = ''

    def onProgress(self, s):
        if s['state'] == 'Downloading':
            self.speed = s['speed']
            self.eta = s['eta']
            self.percent = s['per']
            self.fire()
        else:
            self.reset()

    def _run(self):
        try:
            self.qualities = json.dumps(self.streamdown.getQualities())
            self.streamdown.download()
        finally:
            self.streamdown.close()

    def stop(self):
        super().stop()
        self.streamdown.close()

class TaskManager(object):
    __doc__ = 'docstring for TaskManager'

    def __init__(self):
        self.tasks_activating = {}
        self.worker_mgr = None

    def setWorkerMgr(self, worker_mgr):
        self.worker_mgr = worker_mgr

    def register(self, task):
        self.tasks_activating[task.id] = task
        task.register(self)

    def unregister(self, task):
        task.unregister(self)
        if task.id in self.tasks_activating:
            del self.tasks_activating[task.id]

    def update(self, task):
        if task.status() == ERROR:
            log.error('Unable handle task id %s url %s with error %s', task.id, task.url, task.error)
            self.unregister(task)
            TaskDB.update(task.id, status=task.status(), qualities=task.qualities, speed='', eta='', percent='', error=task.error)
            return
        if task.status() in [COMPLETED, STOPPED]:
            self.unregister(task)
            TaskDB.update(task.id, status=task.status(), qualities=task.qualities, speed='', eta='', percent='', error='')
            return
        TaskDB.update(task.id, status=task.status(), qualities=task.qualities, speed=task.speed, eta=task.eta, percent=task.percent)

    def create_task(self, params, override=False):
        if 'album_name' in params and 'file_name' in params:
            album_name = params.pop('album_name')
            file_name = params.pop('file_name')
            if isinstance(album_name, str):
                path = os.path.join(app_settings.download_dir, album_name, file_name)
            else:
                path = os.path.join(app_settings.download_dir, *album_name, *(file_name,))
        elif 'file_name' in params:
            file_name = params.pop('file_name')
            path = os.path.join(app_settings.download_dir, file_name)
        elif 'path' in params:
            path = os.path.join(app_settings.download_dir, path)
        else:
            raise Exception('path not found in post data')
        if not path.endswith('.mp4'):
            path += '.mp4'
        dir_path = sanitizePath(os.path.dirname(path))
        file_name = cleanName(os.path.basename(path))
        path = longPath(os.path.join(dir_path, file_name))
        mkdirs(dir_path)
        url = params['url']
        tid = TaskDB.makeTaskId(url.encode('latin1'))
        try:
            TaskDB.getTask(tid)
            if override:
                TaskDB.update(tid, headers=json.dumps(params['headers']), path=path, status=QUEUING, error='')
                return tid
            raise TaskWasExisted(tid)
        except TaskNotExist:
            TaskDB.create(tid, url, json.dumps(params['headers']), path)
            return tid

    def override_task(self, params):
        self.create_task(params, True)

    def create_multi_tasks(self, tasks_info):
        tasks_exsited = []
        tasks_new = []
        for task_info in tasks_info:
            override = task_info.pop('override', False)
            try:
                tasks_new.append(self.create_task(task_info.copy(), override))
            except TaskWasExisted as err:
                task_info['tid'] = err.tid
                tasks_exsited.append(task_info)
        if tasks_exsited:
            raise TaskListWasExisted(tasks_exsited)
        return tasks_new

    def resume_task(self, tid, params):
        if tid in self.tasks_activating and self.tasks_activating[tid].isRunning():
            raise Exception('Task %s still running' % tid)
        force_run = params.pop('force_run')
        path = os.path.join(app_settings.download_dir, params['path'])
        dir_path = sanitizePath(os.path.dirname(path))
        file_name = cleanName(os.path.basename(path))
        params['path'] = longPath(os.path.join(dir_path, file_name))
        mkdirs(dir_path)
        params.pop('url', None)
        params['status'] = QUEUING
        params['headers'] = json.dumps(params['headers'])
        params['error'] = ''
        TaskDB.update(tid, **params)
        if force_run:
            self.worker_mgr.force_run_task(TaskDB.getTask(tid))

    def stop_task(self, tid):
        if tid in self.tasks_activating:
            self.tasks_activating[tid].stop()
        else:
            TaskDB.update(tid, status=STOPPED)

    def delete_task(self, tid):
        if tid in self.tasks_activating:
            self.tasks_activating[tid].stop()
        TaskDB.delete(tid)

    def stop_all(self):
        TaskDB.stop_tasks()
        for task in list(self.tasks_activating.values()):
            task.stop()

    def get_task(self, tid):
        return TaskDB.getTask(tid).serialize()

    def get_tasks_list(self):
        return [t.serialize() for t in TaskDB.getAllTask()]

