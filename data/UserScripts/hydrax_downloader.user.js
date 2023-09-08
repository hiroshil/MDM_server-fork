// ==UserScript==
// @name         hydrax downloader
// @namespace    hydrax
// @version      2.2.1
// @description  hydrax downloader
// @author       NguyenKhong
// @match        https://geoip.redirect-ads.com/*
// @match        https://nazarickol.com/*
// @match        https://player-cdn.com/*
// @match        https://playhydrax.com/*
// @match        https://freeplayervideo.com/*
// @match        https://abysscdn.com/*
// @resource     sweetalert2 https://cdnjs.cloudflare.com/ajax/libs/limonte-sweetalert2/8.11.8/sweetalert2.all.min.js
// @downloadURL  http://127.0.0.1:12000/userscripts/hydrax_downloader.user.js
// @updateURL    http://127.0.0.1:12000/userscripts/hydrax_downloader.user.js
// @grant        unsafeWindow
// @grant        GM_xmlhttpRequest
// @run-at       document-start
// @grant        GM_getResourceText
// @grant        GM_registerMenuCommand
// @grant        GM_openInTab
// @connect      127.0.0.1
// ==/UserScript==


const SERVER = "http://127.0.0.1:12000";
const document = unsafeWindow.document;
const setTimeout = unsafeWindow.setTimeout;

function open_task_monitor(){
    GM_openInTab(`${SERVER}/`);
}

GM_registerMenuCommand("Open dashboard", open_task_monitor);

function $(selector, node=document){
    return node.querySelector(selector);
}

function $$(selector, node=document){
    return node.querySelectorAll(selector);
}

Object.assign($, {
    create: function(tag, attrs = {}){
       let elem = document.createElement(tag);
       Object.assign(elem, attrs);
       if(attrs.appendBody){
           document.body.appendChild(elem);
       }
       if(attrs.appendHead){
           document.head.appendChild(elem);
       }
       return elem;
    },
    ready: function(callback){
       document.addEventListener("DOMContentLoaded", callback);
    },
    addStyle: function(source){
        if(source.startsWith("http") || source.startsWith("blob:")){
            $.create("link", {
                rel: "stylesheet",
                href: source,
                appendHead: true,
            });
        }else{
            $.create("style", {
                innerText: source,
                type: "text/css",
                appendHead: true,
            });
        }
    },
    http: async function(url, options = {}){
        const default_options = {method: "GET", body: null, headers: {"Content-Type": "application/json"}, timeout: 5000};
        options = Object.assign(default_options, options);
        return new Promise(function(resolve, reject){
            GM_xmlhttpRequest({
                url: url,
                method: options.method,
                headers: options.headers,
                data: options.body,
                timeout: options.timeout,
                onload: function(res){
                    const resp = {raw: res.response, json: function(){return JSON.parse(res.responseText);}}
                    if (res.status === 200){
                        resp.ok = true;
                        resolve(resp);
                    }else{
                        resp.ok = false;
                        reject(resp);
                    }
                },
                onerror: function(res){
                    const resp = {ok: false, raw: res.response}
                    reject(resp);
                },
                ontimeout: function(){
                    const resp = {ok: false, raw: "request timeout"}
                    reject(resp);
                }
            });
        })
    }
});

let sweetalert2 = GM_getResourceText("sweetalert2");
eval(`(function(){${sweetalert2}}).bind(window)();`);

async function showUiDownload(){
    let result = await swal.fire({
        title: 'Enter file name',
        input: 'text',
        inputAttributes: {
            autocapitalize: 'off'
        },
        showCancelButton: true,
        confirmButtonText: 'OK',
        showLoaderOnConfirm: true,
        allowOutsideClick: () => !swal.isLoading(),
        preConfirm: function(value) {
            if (!value) {
                swal.showValidationMessage("File name is empty");
                return null;
            }
            return value;
        }
    });
    if(!result.value){
        return;
    }
    swal.fire({
        title: "Đợi một chút nhé!",
        text: "Đang truyền dữ liệu cho server",
        onOpen: function(){swal.showLoading();}
    });
     let headers = {
        "User-Agent": navigator.userAgent,
        "Referer": location.href
    }
    let data = {
        headers: headers,
        file_name: result.value,
        url: window.location.href
    }
    try{
        await $.http(`${SERVER}/task`, {
            method: "POST",
            body: JSON.stringify(data)
        });
        swal.fire({type: "success", title: "Thành công", text: "OK", timer: 3000});
    }catch(err){
        swal.fire({type: "error", title: "Lỗi", text: err.raw, timer: 12000});
    }
}

function AddButtonDownload(player){
    if(!$("div[button=_btn_download]")){
        player.addButton(
            "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjYwOS40IDY0NS44IDkzLjIgMTAwIj4NCiAgPHBhdGggZmlsbD0iI2ZmZiIgZD0iTTY5Ni4yIDc0NS44SDYxNmMtMy43IDAtNi42LTIuOS02LjYtNi42di0yNi43YzAtMy43IDIuOS02LjYgNi42LTYuNiAzLjcgMCA2LjYgMi45IDYuNiA2LjZ2MjBoNjYuN3YtMjBjMC0zLjcgMi45LTYuNiA2LjYtNi42IDMuNyAwIDYuNiAyLjkgNi42IDYuNnYyNi43Yy4zIDMuNy0yLjYgNi42LTYuMyA2LjZ6bS0zNi0zOC4zYy0yLjMgMi4xLTYgMi4xLTguNCAwTDYzMSA2ODguNGMtMi4zLTIuMS0yLjMtNS40IDAtNy42czYtMi4xIDguNCAwbDkuOSA5LjF2LTM3LjVjMC0zLjcgMi45LTYuNiA2LjYtNi42czYuNiAyLjkgNi42IDYuNnYzNy40bDkuOS05LjFjMi4zLTIuMSA2LTIuMSA4LjQgMCAyLjMgMi4xIDIuMyA1LjQgMCA3LjZsLTIwLjYgMTkuMnoiLz4NCjwvc3ZnPg0K",
            "Download Video",
            showUiDownload,
            "_btn_download"
        );
    }
}

function catchJwplayer(){
    Object.defineProperty(unsafeWindow, "jwplayer", {
        set: function(value){
            this._j = value;
            this._ev_on = false;
        },
        get: function(){
            let self = this;
            let jwplayer = self._j;
            if(typeof jwplayer == "function" && jwplayer().on && self._ev_on == false){
                self._ev_on = true;
                let player = jwplayer();
                player.on("ready", function(){
                    AddButtonDownload(player)
                });
                player.on("remove", function(){
                    self._ev_on = false;
                });
            }
            return jwplayer;
        }
    },
    {
        configurable: true,
        writable: true,
    });
}

catchJwplayer();