import os
import logging
import logConfig
from flask import Flask, request, render_template, jsonify, send_file
from appSettings import app_settings
from exceptions import TaskNotExist, TaskListWasExisted
from constants import STATUS_RESP_SUCCESS
CURRENT_DIR = os.getcwd()
app = Flask(__name__, static_folder=os.path.join(CURRENT_DIR, 'data', 'static'), template_folder=os.path.join(CURRENT_DIR, 'data', 'templates'))
log = logging.getLogger('web')
task_mgr = None

@app.after_request
def disableCachingAndCors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['Cache-Control'] = 'public, max-age=0'
    return resp

@app.errorhandler(Exception)
def handleException(err):
    log.error(err)
    return (jsonify(error={'msg': str(err)}), 500)

@app.errorhandler(TaskNotExist)
def handleTaskNotExist(err):
    log.error(err)
    return (jsonify(error={'msg': str(err)}), 404)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/task/list', methods=['GET'])
def getAllTasks():
    return jsonify(task_mgr.get_tasks_list())

@app.route('/task/batch', methods=['POST'])
def add_multi_tasks():
    try:
        taskids_new = task_mgr.create_multi_tasks(request.get_json())
    except TaskListWasExisted as err:
        return (jsonify(error={'tasks': err.tasks, 'msg': str(err)}), 500)
    return jsonify(status=STATUS_RESP_SUCCESS, tids=taskids_new)

@app.route('/task/batch/stop', methods=['PUT'])
def stop_all_tasks():
    task_mgr.stop_all()
    return jsonify(status=STATUS_RESP_SUCCESS, data=task_mgr.get_tasks_list())

@app.route('/task', methods=['POST'])
def add_task():
    tid = task_mgr.create_task(request.get_json())
    return jsonify(status=STATUS_RESP_SUCCESS, tid=tid)

@app.route('/task/<tid>', methods=['GET'])
def get_task_by_id(tid):
    return jsonify(status=STATUS_RESP_SUCCESS, data=task_mgr.get_task(tid))

@app.route('/task/<tid>', methods=['PUT'])
def update_task(tid):
    task_mgr.override_task(request.get_json())
    return jsonify(status=STATUS_RESP_SUCCESS)

@app.route('/task/<tid>', methods=['DELETE'])
def delete_task(tid):
    task_mgr.delete_task(tid)
    return jsonify(status=STATUS_RESP_SUCCESS)

@app.route('/task/<tid>/stop', methods=['PUT'])
def stop_task(tid):
    task_mgr.stop_task(tid)
    return jsonify(status=STATUS_RESP_SUCCESS)

@app.route('/task/<tid>/resume', methods=['PUT'])
def resume_task(tid):
    task_mgr.resume_task(tid, request.get_json())
    return jsonify(status=STATUS_RESP_SUCCESS)

@app.route('/config', methods=['GET', 'POST'])
def setting_handler():
    if request.method == 'GET':
        return jsonify(status=STATUS_RESP_SUCCESS, config=app_settings.dump())
    app_settings.load(request.get_data(as_text=True))
    logConfig.setup(app_settings.log_level)
    return jsonify(status=STATUS_RESP_SUCCESS)

@app.route('/favicon.ico')
def favicon():
    return send_file(os.path.join(os.getcwd(), 'data', 'static', 'imgs', 'logo.jpg'))

@app.route('/userscripts/<string:user_script>', methods=['GET'])
def install_code(user_script):
    if user_script.endswith('.user.js'):
        path = os.path.join(os.getcwd(), 'data', 'UserScripts', user_script)
        if os.path.exists(path):
            return send_file(path)
    return ('Forbidden', 403)

def run(task_manager, host, port):
    global task_mgr
    task_mgr = task_manager
    app.run(host, port, False)

