import os
import subprocess
import shutil
import zipfile
import uuid
import re
import json
import tempfile
import threading
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import uvicorn
from PIL import Image, ImageOps
try:
    from pptx import Presentation
    from pptx.util import Inches
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

import sys

# PyInstaller Path Fix
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    os.environ["PATH"] += os.pathsep + sys._MEIPASS

try:
    import webview
except ImportError:
    pass

# FFMPEG check taaki crash na ho
if not shutil.which("ffmpeg"):
    print("⚠️ WARNING: FFmpeg is not installed or not in PATH! Slide extraction will fail.")

app = FastAPI(title="YT Smart Extractor Ultimate")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

TEMP_DIR = tempfile.gettempdir()
HISTORY_FILE = os.path.join(TEMP_DIR, "yt_extractor_history.json")

class GenerateData(BaseModel):
    task_id: str
    selected_files: list[str]
    format: str
    title: str
    invert_colors: bool = False
    layout: int = 1

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    return []

def save_history(entry):
    hist = load_history()
    hist.insert(0, entry)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(hist[:20], f) # Keep last 20

def cleanup_file(path: str):
    try:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
    except Exception:
        pass

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ultimate YT Extractor Pro</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: { gray: { 900: '#111827', 800: '#1f2937', 700: '#374151' } },
                    animation: { 'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite' }
                }
            }
        }
    </script>
    <style>
        body { background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); color: #f8fafc; font-family: 'Inter', sans-serif; user-select: none; overflow-x: hidden; }
        .glass { background: rgba(30, 41, 59, 0.65); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
        .tab-btn { transition: all 0.3s ease; position: relative; }
        .tab-btn::after { content: ''; position: absolute; bottom: -4px; left: 0; width: 0%; height: 2px; background: #60a5fa; transition: width 0.3s ease; }
        .tab-btn.active { color: #60a5fa; font-weight: 700; }
        .tab-btn.active::after { width: 100%; }
        
        .slide-card { position: relative; cursor: grab; transition: all 0.2s ease; border-radius: 0.5rem; }
        .slide-card:active { cursor: grabbing; transform: scale(0.95) rotate(-2deg); z-index: 10; }
        .slide-card.dragging { opacity: 0.4; border: 2px dashed #60a5fa; transform: scale(0.9); }
        .slide-card:hover { transform: translateY(-4px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3); }
        
        .delete-btn { position: absolute; top: -8px; right: -8px; background: #ef4444; color: white; border-radius: 50%; width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; cursor: pointer; opacity: 0; transition: all 0.2s; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .slide-card:hover .delete-btn { opacity: 1; transform: scale(1.1); }
        .delete-btn:hover { background: #dc2626; transform: scale(1.2) !important; }
        
        .loader { border: 3px solid rgba(255,255,255,0.1); border-top: 3px solid #3b82f6; border-radius: 50%; width: 20px; height: 20px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        
        .app-header { -webkit-app-region: drag; }
        .no-drag { -webkit-app-region: no-drag; }
        .invert-preview { filter: invert(1) hue-rotate(180deg) contrast(1.1); }
        
        /* Custom Scrollbar */
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.2); border-radius: 10px; }
        ::-webkit-scrollbar-thumb { background: rgba(96, 165, 250, 0.5); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(96, 165, 250, 0.8); }
    </style>
</head>
<body class="min-h-screen flex flex-col items-center py-6 px-4">
    <div class="w-full max-w-6xl glass rounded-2xl p-6 flex flex-col h-[90vh]">
        
        <!-- Header -->
        <div class="app-header cursor-move pb-4 border-b border-white/10 flex justify-between items-center mb-6">
            <div class="flex items-center gap-3">
                <div class="bg-blue-500/20 p-2 rounded-lg"><i data-lucide="youtube" class="text-blue-400 w-8 h-8"></i></div>
                <h1 class="text-3xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400">
                    YT Extractor Pro
                </h1>
            </div>
            <div class="flex gap-6 no-drag">
                <button onclick="switchTab('extract')" id="tab-extract" class="tab-btn active text-slate-400 flex items-center gap-2"><i data-lucide="search" class="w-4 h-4"></i> Extractor</button>
                <button onclick="switchTab('editor')" id="tab-editor" class="tab-btn text-slate-400 hidden flex items-center gap-2"><i data-lucide="layout-grid" class="w-4 h-4"></i> Pro Editor</button>
                <button onclick="switchTab('history')" id="tab-history" class="tab-btn text-slate-400 flex items-center gap-2"><i data-lucide="history" class="w-4 h-4"></i> History</button>
            </div>
        </div>

        <!-- TAB 1: EXTRACTOR -->
        <div id="view-extract" class="flex-1 overflow-y-auto no-drag space-y-6">
            <div class="flex gap-4">
                <div class="relative flex-1">
                    <i data-lucide="link" class="absolute left-4 top-3.5 text-slate-400 w-5 h-5"></i>
                    <input type="text" id="urlInput" placeholder="Paste YouTube Link Here (e.g., https://youtu.be/...)" style="user-select: text;" 
                           class="w-full bg-gray-900/50 border border-gray-700/50 rounded-xl pl-12 pr-4 py-3.5 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all shadow-inner text-sm">
                </div>
                <button onclick="fetchInfo()" class="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 px-8 rounded-xl font-bold shadow-lg shadow-blue-900/50 flex items-center gap-2 transition-all active:scale-95 text-sm">
                    <i data-lucide="download-cloud" class="w-5 h-5"></i> Fetch Data
                </button>
            </div>

            <div id="settingsPanel" class="hidden grid grid-cols-1 md:grid-cols-3 gap-6 opacity-0 translate-y-4 transition-all duration-500">
                <!-- Video Preview -->
                <div class="col-span-1 bg-gray-900/80 rounded-xl overflow-hidden border border-gray-700/50 shadow-xl flex flex-col">
                    <iframe id="videoPlayer" class="w-full aspect-video pointer-events-auto" src="" frameborder="0" allowfullscreen></iframe>
                    <div class="p-4 bg-gray-800/40 flex-1">
                        <h3 id="vidTitle" class="font-bold text-sm line-clamp-2 mb-1" title="Title">Title</h3>
                        <p id="vidAuthor" class="text-xs text-blue-400 font-medium">Channel</p>
                    </div>
                </div>

                <!-- Advanced Settings -->
                <div class="col-span-2 bg-gray-900/60 p-6 rounded-xl border border-gray-700/50 flex flex-col justify-between shadow-xl">
                    <div>
                        <h3 class="text-sm font-bold text-slate-300 uppercase tracking-widest border-b border-gray-700/50 pb-3 mb-4 flex items-center gap-2">
                            <i data-lucide="settings-2" class="w-4 h-4 text-purple-400"></i> Extraction Settings
                        </h3>
                        
                        <div class="grid grid-cols-2 gap-5">
                            <div class="bg-gray-800/50 p-3 rounded-lg border border-gray-700/30">
                                <label class="block text-xs text-slate-400 mb-2 flex items-center gap-2"><i data-lucide="scissors" class="w-3 h-3"></i> Trim Video</label>
                                <div class="flex gap-2">
                                    <input type="text" id="timeStart" placeholder="Start (00:00)" style="user-select: text;" class="w-1/2 bg-gray-900 rounded p-2 text-xs border border-gray-700 focus:border-blue-500 outline-none">
                                    <span class="text-slate-500 self-center">-</span>
                                    <input type="text" id="timeEnd" placeholder="End (10:00)" style="user-select: text;" class="w-1/2 bg-gray-900 rounded p-2 text-xs border border-gray-700 focus:border-blue-500 outline-none">
                                </div>
                            </div>
                            
                            <div class="bg-gray-800/50 p-3 rounded-lg border border-gray-700/30">
                                <label class="block text-xs text-slate-400 mb-2 flex items-center gap-2"><i data-lucide="activity" class="w-3 h-3"></i> Capture Mode</label>
                                <select id="slideRate" class="w-full bg-gray-900 rounded p-2 text-xs border border-gray-700 focus:border-blue-500 outline-none text-slate-200">
                                    <option value="smart" selected>🤖 Smart Detect (Scene Change)</option>
                                    <option value="30">⏱️ Auto: Every 30s</option>
                                    <option value="10">⏱️ Auto: Every 10s</option>
                                    <option value="5">⏱️ Auto: Every 5s</option>
                                </select>
                            </div>

                            <div class="bg-gray-800/50 p-3 rounded-lg border border-gray-700/30">
                                <label class="block text-xs text-slate-400 mb-2 flex justify-between">
                                    <span><i data-lucide="sliders" class="w-3 h-3 inline mr-1"></i> AI Sensitivity</span>
                                    <span id="sensValue" class="text-blue-400 font-mono">0.15</span>
                                </label>
                                <input type="range" id="sensitivity" min="0.05" max="0.30" step="0.05" value="0.15" class="w-full accent-blue-500" oninput="document.getElementById('sensValue').innerText = this.value">
                            </div>

                            <div class="bg-gray-800/50 p-3 rounded-lg border border-gray-700/30 flex flex-col justify-center">
                                <label class="block text-xs text-slate-400 mb-2"><i data-lucide="sparkles" class="w-3 h-3 inline mr-1"></i> Pro Filters (Coming Soon)</label>
                                <div class="flex gap-2 text-[10px]">
                                    <span class="bg-gray-900 px-2 py-1.5 rounded border border-gray-700 opacity-50 cursor-not-allowed">👤 Ignore Faces</span>
                                    <span class="bg-gray-900 px-2 py-1.5 rounded border border-gray-700 opacity-50 cursor-not-allowed">📄 Enhance Text</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <button id="extractBtn" onclick="startExtraction()" class="mt-5 w-full bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 py-3.5 rounded-xl font-bold shadow-lg shadow-emerald-900/30 transition-all hover:-translate-y-0.5 active:translate-y-0 flex justify-center items-center gap-2">
                        <i data-lucide="zap" class="w-5 h-5"></i> Start Smart Extraction
                    </button>
                </div>
            </div>
            
            <!-- Illustration for empty state -->
            <div id="emptyState" class="flex flex-col items-center justify-center py-20 opacity-50">
                <i data-lucide="monitor-play" class="w-24 h-24 text-slate-600 mb-4"></i>
                <p class="text-slate-400 font-medium">Paste a link above to fetch video details</p>
            </div>
        </div>

        <!-- TAB 2: PRO EDITOR -->
        <div id="view-editor" class="flex-1 overflow-hidden no-drag hidden flex flex-col">
            <div class="flex flex-col md:flex-row justify-between items-start md:items-end mb-4 bg-gray-900/60 p-4 rounded-xl border border-gray-700/50 shadow-sm gap-4">
                <div class="space-y-1">
                    <h2 class="font-bold text-xl flex items-center gap-2">
                        Slide Editor <span id="slideCount" class="bg-blue-500/20 text-blue-400 text-xs px-2 py-1 rounded-full font-mono"></span>
                    </h2>
                    <p class="text-xs text-slate-400 flex items-center gap-1"><i data-lucide="info" class="w-3 h-3"></i> Drag & Drop to reorder. Delete unwanted slides.</p>
                </div>
                <div class="flex gap-3 items-center flex-wrap">
                    <label class="flex items-center gap-2 text-xs font-semibold bg-gray-800 px-3 py-2 rounded-lg cursor-pointer hover:bg-gray-700 border border-gray-700 transition-colors">
                        <input type="checkbox" id="invertToggle" onchange="toggleInvert()" class="accent-purple-500 w-4 h-4"> 
                        <i data-lucide="moon" class="w-4 h-4 text-purple-400"></i> Dark Mode
                    </label>
                    <select id="exportLayout" class="bg-gray-800 text-xs px-3 py-2 rounded-lg border border-gray-700 outline-none font-semibold hover:border-blue-500 transition-colors cursor-pointer">
                        <option value="1">📄 1 Slide / Page</option>
                        <option value="2">📑 2 Slides / Page</option>
                        <option value="4">🗂️ 4 Slides / Page</option>
                    </select>
                </div>
            </div>
            
            <!-- Grid Scrollable Area -->
            <div class="flex-1 overflow-y-auto pr-2 pb-2">
                <div id="editorGrid" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5 content-start">
                    <!-- Slides injected here -->
                </div>
            </div>

            <!-- Export Buttons -->
            <div class="flex gap-3 pt-4 border-t border-white/10 mt-2 justify-end flex-wrap bg-slate-900/50 p-2 rounded-b-xl">
                <button onclick="clearAllSlides()" class="mr-auto text-red-400 hover:text-red-300 text-sm font-semibold flex items-center gap-1 px-2"><i data-lucide="trash-2" class="w-4 h-4"></i> Clear All</button>
                
                <button onclick="exportFiles('zip')" class="bg-gray-700 hover:bg-gray-600 px-5 py-2.5 rounded-lg font-bold text-sm flex items-center gap-2 shadow-lg transition-colors">
                    <i data-lucide="archive" class="w-4 h-4"></i> ZIP
                </button>
                <button onclick="exportFiles('pptx')" class="bg-orange-600 hover:bg-orange-500 px-5 py-2.5 rounded-lg font-bold text-sm shadow-lg shadow-orange-900/30 flex items-center gap-2 transition-colors">
                    <i data-lucide="presentation" class="w-4 h-4"></i> PPTX
                </button>
                <button onclick="exportFiles('pdf')" class="bg-red-600 hover:bg-red-500 px-6 py-2.5 rounded-lg font-bold text-sm shadow-lg shadow-red-900/30 flex items-center gap-2 transition-transform hover:scale-105 active:scale-95">
                    <i data-lucide="file-text" class="w-4 h-4"></i> Save PDF
                </button>
            </div>
        </div>

        <!-- TAB 3: HISTORY -->
        <div id="view-history" class="flex-1 overflow-y-auto no-drag hidden">
            <h2 class="text-xl font-bold mb-4 flex items-center gap-2 border-b border-gray-700 pb-2"><i data-lucide="clock" class="w-5 h-5 text-blue-400"></i> Recent Extractions</h2>
            <div id="historyList" class="space-y-3 pr-2"></div>
        </div>
    </div>

    <script>
        // Initialize Lucide Icons
        lucide.createIcons();

        let currentTaskId = "";
        let currentTitle = "";
        let slidesArray = [];

        function switchTab(tabId) {
            ['extract', 'editor', 'history'].forEach(t => {
                document.getElementById(`view-${t}`).classList.add('hidden');
                document.getElementById(`tab-${t}`).classList.remove('active', 'text-blue-400');
            });
            document.getElementById(`view-${tabId}`).classList.remove('hidden');
            document.getElementById(`tab-${tabId}`).classList.add('active', 'text-blue-400');
            if(tabId === 'history') loadHistory();
        }

        // Beautiful Notifications using SweetAlert2
        function Toast(msg, icon="info") {
            Swal.fire({
                toast: true, position: 'bottom-end', showConfirmButton: false, timer: 3000,
                timerProgressBar: true, icon: icon, title: msg,
                background: '#1f2937', color: '#fff', iconColor: '#60a5fa'
            });
        }

        function getYTId(url) {
            const match = url.match(/^.*(youtu.be\\/|v\\/|u\\/\\w\\/|embed\\/|watch\\?v=|&v=)([^#&?]*).*/);
            return (match && match[2].length === 11) ? match[2] : null;
        }

        async function fetchInfo() {
            const url = document.getElementById('urlInput').value;
            if(!url) return Toast("Please enter a valid YouTube link!", "warning");
            
            const btn = event.currentTarget;
            const originalHTML = btn.innerHTML;
            btn.innerHTML = '<div class="loader"></div> Fetching...';
            btn.disabled = true;
            
            try {
                const res = await fetch(`/api/info?url=${encodeURIComponent(url)}`);
                const data = await res.json();
                if(res.ok) {
                    const vidId = getYTId(url);
                    if(vidId) document.getElementById('videoPlayer').src = `https://www.youtube.com/embed/${vidId}`;
                    
                    document.getElementById('vidTitle').innerText = data.title;
                    document.getElementById('vidTitle').title = data.title;
                    document.getElementById('vidAuthor').innerText = data.uploader;
                    currentTitle = data.title;
                    
                    document.getElementById('emptyState').classList.add('hidden');
                    const panel = document.getElementById('settingsPanel');
                    panel.classList.remove('hidden');
                    setTimeout(() => { panel.classList.remove('opacity-0', 'translate-y-4'); }, 50);
                    
                    Toast("Video loaded successfully!", "success");
                } else {
                    Swal.fire({ title: 'Error!', text: data.detail, icon: 'error', background: '#1f2937', color: '#fff' });
                }
            } catch(e) { 
                Toast("Connection error. Is backend running?", "error"); 
            }
            btn.innerHTML = originalHTML;
            btn.disabled = false;
        }

        async function startExtraction() {
            const url = document.getElementById('urlInput').value;
            const rate = document.getElementById('slideRate').value;
            const start = document.getElementById('timeStart').value;
            const end = document.getElementById('timeEnd').value;
            const sens = document.getElementById('sensitivity').value;
            
            const btn = document.getElementById('extractBtn');
            btn.innerHTML = '<div class="loader"></div> Extracting... (Might take a few minutes)';
            btn.disabled = true;
            btn.classList.add('opacity-80', 'cursor-not-allowed');

            Swal.fire({
                title: 'Extracting Slides...',
                html: 'Processing video frames. Please do not close this window.',
                allowOutsideClick: false,
                background: '#1f2937', color: '#fff',
                didOpen: () => { Swal.showLoading(); }
            });
            
            let reqUrl = `/api/extract?url=${encodeURIComponent(url)}&rate=${rate}&sens=${sens}`;
            if(start) reqUrl += `&start=${encodeURIComponent(start)}`;
            if(end) reqUrl += `&end=${encodeURIComponent(end)}`;

            try {
                const res = await fetch(reqUrl);
                const data = await res.json();
                if(res.ok) {
                    currentTaskId = data.task_id;
                    slidesArray = data.files;
                    renderEditor();
                    document.getElementById('tab-editor').classList.remove('hidden');
                    switchTab('editor');
                    Swal.close();
                    Toast("Extraction Complete!", "success");
                } else {
                    Swal.fire({ title: 'Extraction Failed', text: data.detail, icon: 'error', background: '#1f2937', color: '#fff' });
                }
            } catch(e) { 
                Swal.fire({ title: 'Error', text: "Server timed out or crashed.", icon: 'error', background: '#1f2937', color: '#fff' });
            }
            
            btn.innerHTML = '<i data-lucide="zap" class="w-5 h-5"></i> Start Smart Extraction';
            lucide.createIcons();
            btn.disabled = false;
            btn.classList.remove('opacity-80', 'cursor-not-allowed');
        }

        function renderEditor() {
            const grid = document.getElementById('editorGrid');
            grid.innerHTML = '';
            document.getElementById('slideCount').innerText = `${slidesArray.length} slides`;
            
            if(slidesArray.length === 0) {
                grid.innerHTML = '<div class="col-span-full text-center py-10 text-slate-500">No slides left.</div>';
                return;
            }
            
            slidesArray.forEach((file, idx) => {
                const div = document.createElement('div');
                div.className = 'slide-card bg-gray-800 overflow-hidden border border-gray-700 shadow-md group';
                div.draggable = true;
                div.dataset.file = file;
                
                div.innerHTML = `
                    <div class="relative w-full pb-[56.25%] bg-black">
                        <img src="/api/image?task_id=${currentTaskId}&file=${file}" class="absolute top-0 left-0 w-full h-full object-cover preview-img transition-transform duration-300 group-hover:scale-105" draggable="false">
                    </div>
                    <div class="p-2 text-center text-[10px] text-slate-400 font-mono truncate border-t border-gray-700 bg-gray-900/50">
                        #${idx + 1} - ${file.replace('.jpg','')}
                    </div>
                    <div class="delete-btn" onclick="deleteSlide('${file}')"><i data-lucide="x" class="w-4 h-4"></i></div>
                `;
                
                // Drag & Drop
                div.addEventListener('dragstart', () => div.classList.add('dragging'));
                div.addEventListener('dragend', () => {
                    div.classList.remove('dragging');
                    updateArrayFromDOM();
                });
                grid.appendChild(div);
            });
            lucide.createIcons();

            const container = document.getElementById('editorGrid');
            container.addEventListener('dragover', e => {
                e.preventDefault();
                const draggingElement = document.querySelector('.dragging');
                if(!draggingElement) return;
                const afterElement = getDragAfterElement(container, e.clientY, e.clientX);
                if (afterElement == null) container.appendChild(draggingElement);
                else container.insertBefore(draggingElement, afterElement);
            });
            toggleInvert();
        }

        function getDragAfterElement(container, y, x) {
            const draggableElements = [...container.querySelectorAll('.slide-card:not(.dragging)')];
            return draggableElements.reduce((closest, child) => {
                const box = child.getBoundingClientRect();
                const offsetX = x - box.left - box.width / 2;
                const offsetY = y - box.top - box.height / 2;
                // Simple heuristic for grid reordering
                const offset = Math.abs(offsetX) + Math.abs(offsetY); 
                if (offset < closest.offset && offsetY < box.height/2 && offsetX < box.width/2) {
                    return { offset: offset, element: child }
                } else return closest;
            }, { offset: Number.POSITIVE_INFINITY }).element;
        }

        function updateArrayFromDOM() {
            const cards = document.querySelectorAll('.slide-card');
            slidesArray = Array.from(cards).map(card => card.dataset.file);
            renderEditor(); // re-render to update index numbers
        }

        function deleteSlide(file) {
            slidesArray = slidesArray.filter(f => f !== file);
            renderEditor();
        }
        
        function clearAllSlides() {
            Swal.fire({
                title: 'Are you sure?', text: "You won't be able to revert this!", icon: 'warning',
                showCancelButton: true, confirmButtonColor: '#ef4444', cancelButtonColor: '#374151',
                confirmButtonText: 'Yes, delete all!', background: '#1f2937', color: '#fff'
            }).then((result) => {
                if (result.isConfirmed) { slidesArray = []; renderEditor(); }
            })
        }

        function toggleInvert() {
            const isChecked = document.getElementById('invertToggle').checked;
            document.querySelectorAll('.preview-img').forEach(img => {
                if(isChecked) img.classList.add('invert-preview');
                else img.classList.remove('invert-preview');
            });
        }

        function triggerConfetti() {
            confetti({ particleCount: 100, spread: 70, origin: { y: 0.6 }, colors: ['#60a5fa', '#a78bfa', '#34d399'] });
        }

        async function exportFiles(format) {
            if(slidesArray.length === 0) return Toast("No slides to export!", "warning");
            
            const invert = document.getElementById('invertToggle').checked;
            const layout = parseInt(document.getElementById('exportLayout').value);
            
            const btn = event.currentTarget;
            const originalHTML = btn.innerHTML;
            btn.innerHTML = '<div class="loader" style="width:16px;height:16px;border-width:2px;"></div>';
            btn.disabled = true;
            
            try {
                const res = await fetch('/api/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_id: currentTaskId, selected_files: slidesArray, format: format, title: currentTitle, invert_colors: invert, layout: layout })
                });
                
                if(res.ok) {
                    const blob = await res.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    const cleanTitle = currentTitle.replace(/[\\\\/*?:"<>|]/g, "_") || "Presentation";
                    a.download = `${cleanTitle}_Slides.${format}`;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    triggerConfetti();
                    Toast(`Downloaded as ${format.toUpperCase()}!`, "success");
                } else {
                    const err = await res.json();
                    Swal.fire('Export Failed', err.detail || 'Unknown error', 'error');
                }
            } catch(e) { Toast("Network Error during export.", "error"); }
            
            btn.innerHTML = originalHTML;
            btn.disabled = false;
        }

        async function loadHistory() {
            const list = document.getElementById('historyList');
            list.innerHTML = '<div class="text-center py-4"><div class="loader border-slate-500 border-t-blue-500"></div></div>';
            
            try {
                const res = await fetch('/api/history');
                const data = await res.json();
                
                list.innerHTML = data.length ? '' : '<div class="text-center py-10 opacity-50"><i data-lucide="ghost" class="w-12 h-12 mx-auto mb-2 text-slate-500"></i><p>No history yet.</p></div>';
                
                data.forEach(item => {
                    list.innerHTML += `
                        <div class="bg-gray-800/80 p-4 rounded-xl border border-gray-700/50 flex justify-between items-center hover:bg-gray-800 transition-colors">
                            <div class="flex items-center gap-4">
                                <div class="bg-blue-900/30 p-2 rounded-lg text-blue-400"><i data-lucide="file-video" class="w-6 h-6"></i></div>
                                <div>
                                    <h4 class="font-bold text-sm text-slate-200 line-clamp-1" title="${item.title}">${item.title}</h4>
                                    <p class="text-xs text-slate-400 mt-1"><i data-lucide="calendar" class="w-3 h-3 inline"></i> ${item.date} &nbsp;•&nbsp; <i data-lucide="layers" class="w-3 h-3 inline"></i> ${item.slides} slides</p>
                                </div>
                            </div>
                        </div>
                    `;
                });
                lucide.createIcons();
            } catch (e) {
                list.innerHTML = '<p class="text-red-400 p-4">Failed to load history.</p>';
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return HTML_TEMPLATE

@app.get("/api/info")
def get_video_info(url: str):
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {"title": info.get('title', 'Unknown'), "uploader": info.get('uploader', 'Unknown')}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/extract")
def extract_slides(url: str, rate: str = "smart", sens: str = "0.15", start: str = None, end: str = None):
    # Check if FFmpeg exists before trying to extract
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=500, detail="FFmpeg is not installed on the system. Please install FFmpeg to use extraction features.")

    task_id = str(uuid.uuid4())[0:8]
    video_template = os.path.join(TEMP_DIR, f"{task_id}_vid.%(ext)s")
    
    dl_opts = {'format': 'bestvideo[height<=480]', 'outtmpl': video_template, 'noplaylist': True}
    
    # Download range arguments (if provided)
    if start or end:
        args = []
        if start: args.extend(['-ss', start])
        if end: args.extend(['-to', end])
        dl_opts['external_downloader_args'] = {'ffmpeg': args}

    try:
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_file = ydl.prepare_filename(info)
            if not video_file.endswith('.webm') and not video_file.endswith('.mp4'):
                video_file = video_file.rsplit('.', 1)[0] + '.mp4'

        out_folder = os.path.join(TEMP_DIR, f"task_{task_id}")
        os.makedirs(out_folder, exist_ok=True)
        
        if rate == "smart":
            vf_filter = f"select='gt(scene,{sens})'"
            vsync = ["-vsync", "vfr"]
        else:
            vf_filter = f"fps=1/{rate}"
            vsync = []
            
        cmd = ["ffmpeg", "-y", "-i", video_file, "-filter:v", vf_filter] + vsync + [os.path.join(out_folder, "slide_%03d.jpg")]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        cleanup_file(video_file)
        files = sorted([f for f in os.listdir(out_folder) if f.endswith('.jpg')])
        
        # Save to history
        save_history({"title": info.get('title', 'Extracted Slides'), "date": time.strftime("%Y-%m-%d %H:%M"), "slides": len(files)})
        
        return {"task_id": task_id, "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/image")
def get_image(task_id: str, file: str):
    path = os.path.join(TEMP_DIR, f"task_{task_id}", file)
    if os.path.exists(path): return FileResponse(path)
    raise HTTPException(status_code=404, detail="Image not found")

@app.get("/api/history")
def get_history():
    return load_history()

@app.post("/api/generate")
def generate_file(data: GenerateData, bg_tasks: BackgroundTasks):
    task_folder = os.path.join(TEMP_DIR, f"task_{data.task_id}")
    if not os.path.exists(task_folder): raise HTTPException(status_code=404, detail="Session expired")

    safe_title = re.sub(r'[\\/*?:"<>|]', "_", data.title)
    out_file = os.path.join(TEMP_DIR, f"{safe_title}_{data.task_id}.{data.format}")

    # Process Images (Invert Colors if needed)
    images = []
    for f in data.selected_files:
        p = os.path.join(task_folder, f)
        if os.path.exists(p):
            img = Image.open(p).convert('RGB')
            if data.invert_colors: img = ImageOps.invert(img)
            images.append(img)
            
    if not images: raise HTTPException(status_code=400, detail="No valid images")

    # Layout processing for PDF (2x2 grid, etc)
    if data.format == "pdf":
        if data.layout > 1:
            processed = []
            for i in range(0, len(images), data.layout):
                batch = images[i:i+data.layout]
                bg_w, bg_h = images[0].size
                if data.layout == 2:
                    canvas = Image.new('RGB', (bg_w, bg_h * 2), (255,255,255))
                    canvas.paste(batch[0], (0, 0))
                    if len(batch)>1: canvas.paste(batch[1], (0, bg_h))
                else: # 4 layout
                    canvas = Image.new('RGB', (bg_w * 2, bg_h * 2), (255,255,255))
                    canvas.paste(batch[0], (0, 0))
                    if len(batch)>1: canvas.paste(batch[1], (bg_w, 0))
                    if len(batch)>2: canvas.paste(batch[2], (0, bg_h))
                    if len(batch)>3: canvas.paste(batch[3], (bg_w, bg_h))
                processed.append(canvas)
            images = processed
            
        images[0].save(out_file, save_all=True, append_images=images[1:])
        mt = 'application/pdf'

    elif data.format == "zip":
        with zipfile.ZipFile(out_file, 'w') as zipf:
            for idx, img in enumerate(images):
                temp_img = os.path.join(TEMP_DIR, f"temp_{idx}.jpg")
                img.save(temp_img)
                zipf.write(temp_img, arcname=data.selected_files[idx])
                os.remove(temp_img)
        mt = 'application/zip'

    elif data.format == "pptx":
        if not HAS_PPTX: raise HTTPException(status_code=400, detail="python-pptx not installed")
        prs = Presentation()
        # Set to 16:9 aspect ratio standard
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5) 
        for img in images:
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            temp_img = os.path.join(TEMP_DIR, f"pptx_temp_{uuid.uuid4().hex[:6]}.jpg")
            img.save(temp_img)
            slide.shapes.add_picture(temp_img, 0, 0, width=prs.slide_width, height=prs.slide_height)
            os.remove(temp_img)
        prs.save(out_file)
        mt = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    
    bg_tasks.add_task(cleanup_file, out_file)
    return FileResponse(path=out_file, filename=os.path.basename(out_file), media_type=mt)

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2)
    try:
        window = webview.create_window('YT Extractor Pro Ultimate', 'http://127.0.0.1:8000', width=1200, height=850)
        webview.start()
    except:
        print("UI module failed. Open http://127.0.0.1:8000 in Chrome/Edge.")
        t.join()
        