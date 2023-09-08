import os
import sys
import logging
import signal
import logConfig
from appSettings import app_settings
from task import TaskManager
from worker import WorkerManager
import hideclick
import web
logging.getLogger('App')
HOST = ('127.0.0.1', 12000)
worker_mgr = None

def menu():
    print("""
 Wellcome MDM > Meo Download Manager <
""")
    print(' Access dashboard: http://%s:%s/' % (HOST[0], HOST[1]))
    for file in os.listdir(os.path.join(os.getcwd(), 'data', 'UserScripts')):
        if file.endswith('.user.js'):
            print(""" To install code go to: http://%s:%s/userscripts/%s
""" % (HOST[0], HOST[1], file))

def signalHander(sig, frame):
    print('Wait for cleanup...')
    if worker_mgr:
        worker_mgr.shutdown()
    print('Stop program!')
    sys.exit(0)

def main():
    global worker_mgr
    os.environ['loadingstop'] = '1'
    os.environ['WERKZEUG_RUN_MAIN'] = 'false'
    signal.signal(signal.SIGINT, signalHander)
    app_settings.checkArgs()
    app_settings.load()
    logConfig.setup(app_settings.log_level)
    task_mgr = TaskManager()
    worker_mgr = WorkerManager(task_mgr)
    worker_mgr.load_task_unfinished()
    worker_mgr.start()
    os.system('cls')
    menu()
    web.run(task_mgr, HOST[0], HOST[1])

if __name__ == '__main__':
    main()
