const SERVER = "";

const FILTER_TYPE = {
    ALL: 1,
    DOWNLOADING: 2,
    COMPLETED: 3,
    ERROR: 4
}

const QUEUING = "Queue"
const RUNNING = "Downloading"
const COMPLETED = "Completed"
const ERROR = "Error"
const STOPPED = "Stopped"

const date_format = function(raw){ this.raw = raw;}
date_format.prototype.toString = function(){
    return (new Date(this.raw*1000)).toLocaleString("vi-VN");
}

const task_seleted_default = {}

var app = new Vue({
    el: '#app',
    data: function() {
        return {
            FILTER: FILTER_TYPE,
            tasks_data: [],
            filter_mode: FILTER_TYPE.ALL,
            toggle_add_task: false,
            toggle_restart_task: false,
            toggle_settings_app: false,
            toggle_about: false,
            selected_task_id: "",
            task_new: { url: "", path: "", headers: "" },
            restart_data: null,
            config_data: null,
            task_headers: [
                {
                    title: "Name",
                    key: "file_name",
                    sortType: "normal",
                },
                {
                    title: "Status",
                    key: "status"
                },
                {
                    title: "Percent",
                    key: "percent"
                },
                {
                    title: "Speed",
                    key: "speed",
                    width: "110px"
                },
                {
                    title: "ETA",
                    key: "eta"
                },
                {
                    title: "Create at",
                    key: "create_at",
                    sortType: "normal",
                    sortMethod: this.columnDateSort.bind(this)
                }
            ],
            task_filtered: []
        }
    },
    mounted: function() {
        let self = this;
        let request_tasks = async function(){
            let resp = await fetch(SERVER + "/task/list");
            self.setTasksData(await resp.json());

        }
        request_tasks();
        setInterval(request_tasks, 3000);
    },
    computed: {
        task_downloading: function() {
            return this.tasks_data.filter(function(task) {
                return task.status === RUNNING ;
            });
        },
        task_completed: function() {
            return this.tasks_data.filter(function(task) {
                return COMPLETED === task.status || STOPPED === task.status;
            });
        },
        task_error: function() {
            return this.tasks_data.filter(function(task) {
                return task.status === ERROR;
            });
        },
        task_seleted: function(){
            let self = this;
            return this.task_filtered.find(function(task) {
                    return task.id === self.selected_task_id;
                });
        }
    },
    methods: {
        setTasksData: function(tasks_data){
            for(let task of tasks_data){
                task.create_at = new date_format(task.create_at);
            }
            this.tasks_data = tasks_data;
            this.filter();
        },
        columnDateSort: function(first_date, second_date, type){
            if(type === "asc"){
                return first_date.raw - second_date.raw;
            }
            return second_date.raw - first_date.raw;
        },
        taskSelected: function(task) {
            this.selected_task_id = task.id;  
        },
        filter: function() {
            switch (this.filter_mode) {
                case FILTER_TYPE.ALL:
                    this.task_filtered = this.tasks_data;
                    break;
                case FILTER_TYPE.DOWNLOADING:
                    this.task_filtered = this.task_downloading;
                    break;
                case FILTER_TYPE.COMPLETED:
                    this.task_filtered = this.task_completed;
                    break;
                case FILTER_TYPE.ERROR:
                    this.task_filtered = this.task_error;
                    break;
            }
        },
        filterSelected: function(mode) {
            this.selected_task_id = "";
            this.$refs.task_table.resetCurrentSelected();
            this.filter_mode = mode;
            this.filter();

        },
        addNewTaskConfirm: async function() {
            // create new task
            this.task_new.headers = this.Text2DictHeader(this.task_new.headers);
            const body = JSON.stringify(this.task_new);
            this.task_new = {url: "", path: "", headers: "" };
            let resp = await fetch(`${SERVER}/task`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: body
            });
            if (resp.ok){
                this.$Notify({title: "Success", message: "Restart task successfully", type: "success"});
            }else{
                let result = await resp.json();
                this.$Notify({title: "Error", message: result.error.msg, type: "error"});
            }
        },
        addNewTaskCancel: function(){
            this.task_new = { url: "", path: "", headers: "" };
        },
        btnRemoveClick: async function(){
            if (!this.task_seleted) {
                this.$Notify({
                    title: "Error",
                    message: "Please select a row",
                    type: "error"
                });
                return;
            }
            try{
                await this.$Modal.confirm({title: "Remove", content: `Do you want remove task url ${this.task_seleted.url} ?`});
                let resp = await fetch(`${SERVER}/task/${this.task_seleted.id}`, {
                    method: "DELETE"
                });
                if (resp.ok){
                    let task_id = this.task_seleted.id;
                    for(let i = 0; i < this.tasks_data.length; ++i){
                        if (this.tasks_data[i].id === task_id){
                            this.tasks_data.splice(i, 1);
                            break;
                        }
                    }
                    this.selected_task_id = "";
                    this.$refs.task_table.resetCurrentSelected();
                    this.$Notify({title: "Success", message: "Delete task successfully", type: "success"});
                }else{
                    let result = await resp.json();
                    this.$Notify({title: "Error", message: result.error.msg, type: "error"});
                }
            }catch(err){}
        },
        btnStopClick: async function(){
            if (!this.task_seleted) {
                this.$Notify({
                    title: "Error",
                    message: "Please select a row",
                    type: "error"
                });
                return;
            }
            if(this.task_seleted.status === COMPLETED){
                this.$Notify({title: "Warning", message: "This task was completed.", type: "warning"});
                return;
            }
            let resp = await fetch(`${SERVER}/task/${this.task_seleted.id}/stop`, {
                method: "PUT"
            });
            if (resp.ok){ 
                this.$Notify({title: "Success", message: "Stop task successfully", type: "success"});
            }else{
                let result = await resp.json();
                this.$Notify({title: "Error", message: result.error.msg, type: "error"});
            }
        },
        btnStopAllClick: async function(){
            let resp = await fetch(`${SERVER}/task/batch/stop`, {
                method: "PUT"
            });
            if (resp.ok){
                let result = await resp.json();
                this.setTasksData(result.data);
                this.$Notify({title: "Success", message: "Stop all task successfully", type: "success"});
            }else{
                let result = await resp.json();
                this.$Notify({title: "Error", message: result.error.msg, type: "error"});
            }
        },
        btnRestartClick: function() {
            let headers = null;
            let lines = [];
            if (this.task_seleted) {
                if(this.task_seleted.status === RUNNING || this.task_seleted.status === QUEUING){
                    this.$Notify({
                        title: "Error",
                        message: "Please stop current task is being selected before restart it",
                        type: "error"
                    });
                    return;
                }
                this.restart_data = {
                    force_run: false,
                    id: this.task_seleted.id,
                    url: this.task_seleted.url,
                    path: this.task_seleted.path,
                    headers: this.Dict2TextHeader(this.task_seleted.headers)
                }
                if(this.task_seleted.qualities && this.task_seleted.qualities.length){
                    let qualities = this.task_seleted.qualities.reverse();
                    this.restart_data.quality = qualities[0];
                    this.restart_data.qualities = qualities;
                }else{
                    this.restart_data.quality = "best";
                }
                this.toggle_restart_task = true;
                return;
            } 
            this.$Notify({
                title: "Error",
                message: "Please select a row",
                type: "error"
            });
            
        },
        btnRestartTaskConfirm: async function() {
            const data_edited = this.restart_data;
            const task_info = {
                quality: data_edited.quality,
                path: data_edited.path,
                headers: this.Text2DictHeader(data_edited.headers),
                force_run: data_edited.force_run
            }
            this.restart_data = null;
            let resp = await fetch(`${SERVER}/task/${data_edited.id}/resume`, {
                method: "PUT",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(task_info)
            });
            if (resp.ok){
                this.$Notify({title: "Success", message: "Restart task successfully", type: "success"});
            }else{
                let result = await resp.json();
                this.$Notify({title: "Error", message: result.error.msg, type: "error"});
            }
        },
        btnCancelRestartTask: function(){
            this.restart_data = null;
        },
        btnSettingClick: async function(){
            let resp = await fetch(`${SERVER}/config`);
            if (resp.ok){
                
                let result = await resp.json();
                this.config_data = result.config;
                this.toggle_settings_app = true;

            }else{
                let result = await resp.json();
                this.$Notify({title: "Error", message: result.error.msg, type: "error"});
            }
        },
        btnSettingsConfirm: async function(){
            delete this.config_data.log_level_name;
            let resp = await fetch(`${SERVER}/config`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(this.config_data)
            });
            if (resp.ok){
                this.config_data = null;
                this.$Notify({title: "Success", message: "Setup settings successfully", type: "success"});
            }else{
                let result = await resp.json();
                this.$Notify({title: "Error", message: result.error.msg, type: "error"});
            }
            this.toggle_settings_app = false;
        },
        btnSettingsCancel: function(){
            this.toggle_settings_app = false;
            this.config_data = null;
        },
        Text2DictHeader(raw){
            let headers = {};
            if (raw){
                let lines = raw.split("\n");
                for (let line of lines){
                    let p = line.split(":");
                    headers[p[0].trim()] = p.slice(1).join(":").trim();
                }
            }
            return headers
        },
        Dict2TextHeader(headers){
            let lines = [];
            for(let key in headers){
                lines.push(`${key}:${headers[key]}`);
            }
            return lines.join("\n");
        }
    }
})