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
import urllib.request
import sys
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import uvicorn
from PIL import Image, ImageOps, ImageChops, ImageStat, ImageEnhance, ImageDraw, ImageFont

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

try:
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    os.environ["PATH"] += os.pathsep + sys._MEIPASS

try:
    import webview
except ImportError:
    pass

TRANSCRIPT_CACHE = {}

def load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"\'')
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception as e:
            print(f"Warning: Could not read .env file: {e}")

load_env_file()

def setup_env():
    BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
    os.makedirs(BIN_DIR, exist_ok=True)
    os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")

    if not shutil.which("ffmpeg"):
        print("⏳ FFmpeg missing! Downloading automatically...")
        try:
            ffmpeg_url = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-win-64.zip"
            zip_path = os.path.join(BIN_DIR, "ffmpeg.zip")
            urllib.request.urlretrieve(ffmpeg_url, zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(BIN_DIR)
            os.remove(zip_path)
            print("✅ FFmpeg successfully installed!")
        except Exception as e:
            print(f"❌ FFmpeg download failed: {e}")

setup_env()

app = FastAPI(title="YT Extractor Pro Ultimate")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

TEMP_DIR = tempfile.gettempdir()
HISTORY_FILE = os.path.join(TEMP_DIR, "yt_extractor_history.json")

class GenerateData(BaseModel):
    task_id: str
    selected_files: list[str]
    format: str
    title: str
    invert_colors: bool = False
    enhance_text: bool = False
    layout: int = 1
    quality: str = "high"
    slide_notes: dict[str, str] = {}
    slide_tags: dict[str, str] = {}
    starred_files: list[str] = []
    author_name: str = ""
    subject_tag: str = ""

class SummaryRequest(BaseModel):
    url: str
    title: str = ""
    api_key: str = None

class ChatRequest(BaseModel):
    url: str
    title: str = ""
    question: str
    api_key: str = None

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(entry):
    hist = load_history()
    hist.insert(0, entry)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(hist[:20], f)

def cleanup_file(path: str):
    try:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
    except Exception:
        pass

def get_video_transcript(url: str):
    if url in TRANSCRIPT_CACHE:
        return TRANSCRIPT_CACHE[url]

    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitlesformat': 'json3/vtt/srt',
        'quiet': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            subtitles = info.get('subtitles') or {}
            auto_caps = info.get('automatic_captions') or {}
            
            target_subs = None
            for lang in ['en', 'hi', 'en-US', 'en-GB', 'es', 'fr']:
                if lang in subtitles:
                    target_subs = subtitles[lang]
                    break
                elif lang in auto_caps:
                    target_subs = auto_caps[lang]
                    break
            
            if not target_subs:
                all_dict = {**subtitles, **auto_caps}
                if all_dict:
                    first_lang = list(all_dict.keys())[0]
                    target_subs = all_dict[first_lang]
            
            if not target_subs:
                return []

            fmt_url = None
            fmt_ext = 'json3'
            for f in target_subs:
                if f.get('ext') == 'json3':
                    fmt_url = f.get('url')
                    fmt_ext = 'json3'
                    break
                elif f.get('ext') == 'vtt':
                    fmt_url = f.get('url')
                    fmt_ext = 'vtt'
            
            if not fmt_url and target_subs:
                fmt_url = target_subs[0].get('url')
                fmt_ext = target_subs[0].get('ext', 'json3')
                
            if not fmt_url:
                return []
                
            req = urllib.request.Request(fmt_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode('utf-8')
                
            entries = []
            if 'json3' in fmt_ext or content.strip().startswith('{'):
                data = json.loads(content)
                for event in data.get('events', []):
                    start = event.get('tStartMs', 0) / 1000.0
                    duration = event.get('dDurationMs', 0) / 1000.0
                    segs = event.get('segs', [])
                    text = "".join([s.get('utf8', '') for s in segs if s.get('utf8')]).strip()
                    text = re.sub(r'\s+', ' ', text)
                    if text and text != '\n':
                        entries.append({"start": round(start, 2), "duration": round(duration, 2), "text": text})
            else:
                lines = content.splitlines()
                current_start = 0.0
                for line in lines:
                    time_match = re.search(r'(\d+):(\d+):(\d+\.\d+)\s*-->\s*(\d+):(\d+):(\d+\.\d+)', line)
                    if not time_match:
                        time_match = re.search(r'(\d+):(\d+\.\d+)\s*-->\s*(\d+):(\d+\.\d+)', line)
                    if time_match:
                        groups = time_match.groups()
                        if len(groups) == 6:
                            current_start = int(groups[0])*3600 + int(groups[1])*60 + float(groups[2])
                        else:
                            current_start = int(groups[0])*60 + float(groups[1])
                    elif line.strip() and not line.startswith('WEBVTT') and not line.isdigit() and '-->' not in line:
                        clean_text = re.sub(r'<[^>]+>', '', line.strip())
                        if clean_text:
                            entries.append({"start": round(current_start, 2), "duration": 3.0, "text": clean_text})
            
            TRANSCRIPT_CACHE[url] = entries
            return entries
    except Exception as e:
        print(f"Error fetching transcript: {e}")
        return []

def generate_smart_summary(transcript: list, title: str, api_key: str = None):
    if not transcript:
        return {
            "executive_summary": "No transcript or subtitles could be found for this video. Summary unavailable.",
            "key_takeaways": ["Make sure the video has public captions or auto-generated subtitles."],
            "chapters": [],
            "mindmap": "mindmap\n  root((No Transcript))\n    Unavailable",
            "quiz": [],
            "stats": {"word_count": 0, "read_time_min": 0, "segments": 0},
            "source": "none"
        }

    full_text = " ".join([item['text'] for item in transcript])
    words_list = re.findall(r'\w+', full_text)
    word_count = len(words_list)
    read_time = max(1, round(word_count / 150))
    stats = {"word_count": word_count, "read_time_min": read_time, "segments": len(transcript)}

    if api_key and api_key.strip():
        try:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key.strip()}"
            prompt = f"""Analyze the video transcript titled '{title}'.

Video Transcript:
{full_text[:14000]}

Respond ONLY in valid JSON with this exact schema:
{{
  "executive_summary": "3-4 sentence comprehensive overview of the core topic, thesis, and takeaways.",
  "key_takeaways": [
    "Key concept 1 explained clearly",
    "Key concept 2 explained clearly",
    "Key concept 3 explained clearly",
    "Key concept 4 explained clearly"
  ],
  "chapters": [
    {{"time": "00:00", "seconds": 0, "title": "Introduction and Setup"}},
    {{"time": "02:30", "seconds": 150, "title": "Core Demonstration"}}
  ],
  "mindmap": "mindmap\\n  root(({title[:20]}))\\n    Overview\\n      Core Topic\\n    Key Concepts\\n      Main Takeaways",
  "quiz": [
    {{
      "question": "Sample quiz question based on transcript?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct": 0,
      "explanation": "Explanation of correct answer."
    }}
  ]
}}"""

            payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode('utf-8')
            req = urllib.request.Request(gemini_url, data=payload, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_data = json.loads(resp.read().decode('utf-8'))
                raw_text = resp_data['candidates'][0]['content']['parts'][0]['text']
                clean_json = re.sub(r'```(json)?', '', raw_text).strip()
                res_dict = json.loads(clean_json)
                res_dict['stats'] = stats
                res_dict['source'] = 'gemini'
                return res_dict
        except Exception as e:
            print(f"Gemini API error, falling back to local NLP: {e}")

    words = [w.lower() for w in words_list]
    stopwords = set(["the", "a", "an", "is", "are", "was", "were", "and", "or", "in", "to", "of", "that", "this", "it", "for", "on", "with", "as", "at", "by", "from", "be", "have", "has", "you", "we", "they", "i", "my", "your", "so", "if", "out", "about", "like", "just", "what", "which", "how", "when", "there", "can", "will", "all", "one", "also", "here", "more", "then", "them", "up", "some", "no", "not", "do", "get", "go", "see", "know", "think", "make", "us", "our"])
    
    freq = {}
    for w in words:
        if w not in stopwords and len(w) > 2:
            freq[w] = freq.get(w, 0) + 1
            
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', full_text) if len(s.strip()) > 15]
    sent_scores = []
    for s in sentences:
        s_words = re.findall(r'\w+', s.lower())
        score = sum(freq.get(w, 0) for w in s_words if w in freq) / (len(s_words) + 1)
        sent_scores.append((score, s))
        
    sent_scores.sort(reverse=True, key=lambda x: x[0])
    top_sentences = [s for _, s in sent_scores[:4]]
    executive_summary = " ".join(top_sentences) if top_sentences else full_text[:300] + "..."

    top_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]
    key_takeaways = []
    for kw, _ in top_keywords:
        matching_sents = [s for s in sentences if kw in s.lower()]
        if matching_sents:
            key_takeaways.append(f"📌 **{kw.capitalize()}**: {matching_sents[0][:130]}")
            
    if not key_takeaways:
        key_takeaways = [f"• {s[:100]}" for s in top_sentences[:4]]

    chapters = []
    if transcript:
        total_items = len(transcript)
        step = max(1, total_items // 5)
        for idx in range(0, total_items, step):
            item = transcript[idx]
            sec = int(item['start'])
            m, s = divmod(sec, 60)
            h, m = divmod(m, 60)
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            preview_text = item['text'][:55] + "..."
            chapters.append({"time": time_str, "seconds": sec, "title": preview_text})

    clean_title = re.sub(r'[^a-zA-Z0-9 ]', '', title[:20]) or "Video Content"
    mm_nodes = [kw.capitalize() for kw, _ in top_keywords[:4]]
    mindmap = f"mindmap\n  root(({clean_title}))\n"
    for node in mm_nodes:
        mindmap += f"    {node}\n"

    quiz = []
    if top_keywords and len(top_keywords) >= 3:
        kw1 = top_keywords[0][0].capitalize()
        kw2 = top_keywords[1][0].capitalize()
        kw3 = top_keywords[2][0].capitalize()
        quiz.append({
            "question": f"Which core concept is heavily emphasized in this video?",
            "options": [kw1, "Unrelated Topic", "Random Concept", "Legacy Standard"],
            "correct": 0,
            "explanation": f"'{kw1}' is one of the most frequently referenced terms in the video transcript."
        })
        quiz.append({
            "question": f"What secondary concept is central to understanding the presentation?",
            "options": ["Basic Introduction", kw2, "Future Roadmap", "General Review"],
            "correct": 1,
            "explanation": f"'{kw2}' is discussed in detail during the main presentation segments."
        })
        quiz.append({
            "question": f"Which of the following topics is directly covered?",
            "options": ["Third Party Tools", "System Defaults", kw3, "Manual Overrides"],
            "correct": 2,
            "explanation": f"'{kw3}' is specifically highlighted in the video content."
        })

    return {
        "executive_summary": executive_summary,
        "key_takeaways": key_takeaways,
        "chapters": chapters,
        "mindmap": mindmap,
        "quiz": quiz,
        "stats": stats,
        "source": "smart_nlp"
    }

def answer_video_question(transcript: list, title: str, question: str, api_key: str = None):
    if not transcript:
        return {"answer": "No transcript available for this video to answer questions.", "citations": []}
        
    full_text = " ".join([f"[{int(item['start'])}s] {item['text']}" for item in transcript])
    
    if api_key and api_key.strip():
        try:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key.strip()}"
            prompt = f"""You are an assistant answering user questions about a YouTube video titled '{title}'.
Video transcript with timestamps in seconds:
{full_text[:14000]}

User Question: {question}

Provide a direct, helpful answer based strictly on the transcript. Include timestamp references in [MM:SS] format where appropriate."""
            
            payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode('utf-8')
            req = urllib.request.Request(gemini_url, data=payload, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_data = json.loads(resp.read().decode('utf-8'))
                ans = resp_data['candidates'][0]['content']['parts'][0]['text']
                return {"answer": ans, "citations": []}
        except Exception as e:
            print(f"Gemini Q&A Error: {e}")

    # Offline Smart Natural Language Search Engine (Zero-Config, No API key needed)
    q_lower = question.lower()
    
    # Handle summary/overview questions
    if any(k in q_lower for k in ["summary", "overview", "about", "main topic", "explain", "conclusion", "what is"]):
        ans = f"💡 **Offline Video Context Analysis** for *'{title}'*:\n\n"
        ans += f"This video covers key concepts regarding the presentation. Here are the core highlights discussed in the transcript:\n\n"
        for idx, item in enumerate(transcript[:4]):
            sec = int(item['start'])
            m, s = divmod(sec, 60)
            ans += f"• ⏱️ **[{m:02d}:{s:02d}]**: {item['text']}\n"
        return {"answer": ans, "citations": []}

    # Contextual Search
    q_words = [w for w in re.findall(r'\w+', q_lower) if len(w) > 2 and w not in ["what", "how", "when", "where", "why", "video", "tell", "show"]]
    
    matched_items = []
    for idx, item in enumerate(transcript):
        item_text = item['text'].lower()
        score = sum(2 if w in item_text else 0 for w in q_words)
        if score > 0:
            context_text = item['text']
            if idx > 0: context_text = transcript[idx-1]['text'] + " " + context_text
            if idx < len(transcript)-1: context_text = context_text + " " + transcript[idx+1]['text']
            matched_items.append((score, item, context_text))
            
    matched_items.sort(key=lambda x: x[0], reverse=True)
    top_matches = matched_items[:4]
    
    if not top_matches:
        snippets = []
        for item in transcript[:3]:
            sec = int(item['start'])
            m, s = divmod(sec, 60)
            snippets.append(f"⏱️ **[{m:02d}:{s:02d}]**: \"{item['text']}\"")
        ans = f"I couldn't find exact matches for '{question}', but here is an overview of the video starting topics:\n\n" + "\n\n".join(snippets)
        return {"answer": ans, "citations": []}
        
    citations = []
    snippets = []
    for _, item, ctx in top_matches:
        sec = int(item['start'])
        m, s = divmod(sec, 60)
        time_str = f"{m:02d}:{s:02d}"
        snippets.append(f"⏱️ **[{time_str}]**: \"{ctx}\"")
        citations.append({"time": time_str, "seconds": sec})
        
    ans = f"🔍 **Transcript Context Match for '{question}'**:\n\n" + "\n\n".join(snippets)
    return {"answer": ans, "citations": citations}

def create_pdf_cover_page(width, height, title, author, subject, slide_count):
    canvas = Image.new('RGB', (width, height), (15, 23, 42))
    draw = ImageDraw.Draw(canvas)
    
    # Header bar
    draw.rectangle([0, 0, width, int(height * 0.15)], fill=(139, 92, 246))
    
    # Draw simple text using Pillow default font
    title_text = f"STUDY NOTES: {title[:35]}"
    author_text = f"Author / Presenter: {author or 'YT Extractor Pro'}"
    subject_text = f"Subject: {subject or 'Video Lecture'}"
    count_text = f"Total Slides Extracted: {slide_count}"
    date_text = f"Generated On: {time.strftime('%Y-%m-%d')}"

    y = int(height * 0.3)
    draw.text((int(width * 0.08), y), title_text, fill=(255, 255, 255))
    draw.text((int(width * 0.08), y + 40), subject_text, fill=(168, 85, 247))
    draw.text((int(width * 0.08), y + 80), author_text, fill=(203, 213, 225))
    draw.text((int(width * 0.08), y + 120), count_text, fill=(59, 130, 246))
    draw.text((int(width * 0.08), y + 160), date_text, fill=(148, 163, 184))

    return canvas

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YT Extractor Pro Ultimate</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: { sans: ['Outfit', 'Inter', 'sans-serif'] },
                    colors: { 
                        gray: { 950: '#070a12', 900: '#0b0f19', 850: '#111726', 800: '#172033', 700: '#26334d' }
                    },
                    animation: { 'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite' }
                }
            }
        }
    </script>
    <style>
        :root {
            --primary-accent: #a855f7;
            --primary-glow: rgba(168, 85, 247, 0.4);
            --gradient-from: #a855f7;
            --gradient-to: #3b82f6;
        }

        body { 
            background: radial-gradient(circle at 15% 15%, var(--primary-glow) 0%, transparent 45%),
                        radial-gradient(circle at 85% 85%, rgba(6, 182, 212, 0.12) 0%, transparent 45%),
                        linear-gradient(135deg, #070a12 0%, #0b0f19 50%, #111726 100%);
            color: #f8fafc; font-family: 'Outfit', 'Inter', sans-serif; user-select: none; overflow-x: hidden; 
        }
        
        .glass { 
            background: rgba(17, 23, 38, 0.75); 
            backdrop-filter: blur(24px); 
            border: 1px solid rgba(255, 255, 255, 0.1); 
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7), inset 0 1px 0 rgba(255, 255, 255, 0.1); 
        }

        .tab-btn { transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); position: relative; }
        .tab-btn::after { 
            content: ''; position: absolute; bottom: -4px; left: 50%; transform: translateX(-50%); 
            width: 0%; height: 3px; background: linear-gradient(90deg, var(--primary-accent), #60a5fa); 
            transition: width 0.3s ease; border-radius: 9999px; shadow: 0 0 10px var(--primary-accent);
        }
        .tab-btn.active { color: var(--primary-accent); font-weight: 700; text-shadow: 0 0 12px var(--primary-glow); }
        .tab-btn.active::after { width: 80%; }
        
        .slide-card { position: relative; cursor: pointer; transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1); border-radius: 0.75rem; }
        .slide-card:active { transform: scale(0.96); z-index: 10; }
        .slide-card.dragging { opacity: 0.4; border: 2px dashed var(--primary-accent); transform: scale(0.9); }
        .slide-card:hover { transform: translateY(-4px); box-shadow: 0 15px 30px -5px rgba(0, 0, 0, 0.6), 0 0 15px var(--primary-glow); }
        
        .delete-btn { position: absolute; top: -8px; right: -8px; background: #ef4444; color: white; border-radius: 50%; width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; cursor: pointer; opacity: 0; transition: all 0.2s; box-shadow: 0 4px 6px rgba(0,0,0,0.4); }
        .slide-card:hover .delete-btn { opacity: 1; transform: scale(1.1); }
        .delete-btn:hover { background: #dc2626; transform: scale(1.25) !important; }

        .star-btn { position: absolute; top: -8px; left: -8px; background: #eab308; color: white; border-radius: 50%; width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; cursor: pointer; opacity: 0.8; transition: all 0.2s; box-shadow: 0 4px 6px rgba(0,0,0,0.4); }
        .star-btn.starred { opacity: 1; background: #f59e0b; box-shadow: 0 0 10px #f59e0b; }
        
        .loader { border: 3px solid rgba(255,255,255,0.1); border-top: 3px solid var(--primary-accent); border-radius: 50%; width: 20px; height: 20px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        
        .app-header { -webkit-app-region: drag; }
        .no-drag { -webkit-app-region: no-drag; }
        .invert-preview { filter: invert(1) hue-rotate(180deg) contrast(1.1); }
        
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.2); border-radius: 10px; }
        ::-webkit-scrollbar-thumb { background: var(--primary-glow); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--primary-accent); }

        .btn-glow { transition: all 0.3s ease; }
        .btn-glow:hover { box-shadow: 0 0 20px var(--primary-glow); transform: translateY(-1px); }

        /* 3D Flip Card Styles */
        .perspective-1000 { perspective: 1000px; }
        .transform-style-3d { transform-style: preserve-3d; }
        .backface-hidden { backface-visibility: hidden; }
        .rotate-y-180 { transform: rotateY(180deg); }
    </style>
</head>
<body class="min-h-screen flex flex-col items-center py-4 px-4">
    <div class="w-full max-w-6xl glass rounded-2xl p-5 flex flex-col h-[94vh]">
        
        <!-- Header -->
        <div class="app-header cursor-move pb-3.5 border-b border-white/10 flex flex-col md:flex-row justify-between items-center gap-3 mb-4">
            <div class="flex items-center gap-3">
                <div class="bg-gradient-to-tr from-purple-600 via-indigo-600 to-blue-500 p-2.5 rounded-2xl shadow-lg shadow-purple-500/30">
                    <i data-lucide="youtube" class="text-white w-6 h-6"></i>
                </div>
                <div>
                    <h1 class="text-xl font-black tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-purple-400 via-pink-300 to-blue-400">
                        YT Extractor Pro Ultimate
                    </h1>
                    <p class="text-[11px] text-slate-400 font-medium tracking-wide">Smart Slide Capture • AI Mindmaps • Video Q&A • Study Studio</p>
                </div>
            </div>

            <!-- Theme Accent Switcher, Hotkeys & Tabs -->
            <div class="flex items-center gap-3 no-drag flex-wrap">
                <button onclick="openHotkeyModal()" class="bg-gray-900/80 hover:bg-gray-800 text-slate-300 border border-gray-700/60 px-2.5 py-1 rounded-lg text-[11px] font-semibold flex items-center gap-1">
                    <i data-lucide="keyboard" class="w-3.5 h-3.5 text-purple-400"></i> Hotkeys (?)
                </button>
                <div class="hidden sm:flex items-center gap-1.5 bg-gray-900/80 p-1 rounded-lg border border-gray-700/50 text-[11px]">
                    <span class="text-slate-400 text-[10px] font-semibold px-1">Theme:</span>
                    <button onclick="setThemeAccent('purple')" class="w-3.5 h-3.5 rounded-full bg-purple-500 hover:scale-125 transition-transform" title="Violet Glow"></button>
                    <button onclick="setThemeAccent('cyan')" class="w-3.5 h-3.5 rounded-full bg-cyan-400 hover:scale-125 transition-transform" title="Cyber Cyan"></button>
                    <button onclick="setThemeAccent('emerald')" class="w-3.5 h-3.5 rounded-full bg-emerald-400 hover:scale-125 transition-transform" title="Matrix Emerald"></button>
                    <button onclick="setThemeAccent('rose')" class="w-3.5 h-3.5 rounded-full bg-rose-500 hover:scale-125 transition-transform" title="Rose Gold"></button>
                </div>
                <div class="flex gap-3 md:gap-5 flex-wrap text-xs font-semibold">
                    <button onclick="switchTab('extract')" id="tab-extract" class="tab-btn active text-slate-400 flex items-center gap-1.5 px-1 py-1"><i data-lucide="search" class="w-3.5 h-3.5"></i> Extractor</button>
                    <button onclick="switchTab('summary')" id="tab-summary" class="tab-btn text-slate-400 flex items-center gap-1.5 px-1 py-1"><i data-lucide="sparkles" class="w-3.5 h-3.5 text-purple-400"></i> AI Summary</button>
                    <button onclick="switchTab('transcript')" id="tab-transcript" class="tab-btn text-slate-400 flex items-center gap-1.5 px-1 py-1"><i data-lucide="file-text" class="w-3.5 h-3.5 text-blue-400"></i> Transcript</button>
                    <button onclick="switchTab('editor')" id="tab-editor" class="tab-btn text-slate-400 hidden flex items-center gap-1.5 px-1 py-1"><i data-lucide="layout-grid" class="w-3.5 h-3.5 text-emerald-400"></i> Pro Editor</button>
                    <button onclick="switchTab('history')" id="tab-history" class="tab-btn text-slate-400 flex items-center gap-1.5 px-1 py-1"><i data-lucide="history" class="w-3.5 h-3.5"></i> History</button>
                </div>
            </div>
        </div>

        <!-- TAB 1: EXTRACTOR -->
        <div id="view-extract" class="flex-1 overflow-y-auto no-drag space-y-5 pr-1">
            <div class="flex flex-col sm:flex-row gap-3">
                <div class="relative flex-1">
                    <i data-lucide="link" class="absolute left-4 top-3.5 text-slate-400 w-5 h-5"></i>
                    <input type="text" id="urlInput" placeholder="Paste YouTube Link Here (e.g., https://youtu.be/...)" style="user-select: text;" 
                           class="w-full bg-gray-900/80 border border-gray-700/60 rounded-xl pl-12 pr-4 py-3 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/30 outline-none transition-all shadow-inner text-sm text-slate-100 font-sans">
                </div>
                <div class="flex gap-2">
                    <button onclick="fetchInfo()" class="bg-gradient-to-r from-purple-600 via-indigo-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 px-6 rounded-xl font-bold shadow-lg shadow-purple-900/40 flex items-center gap-2 transition-all active:scale-95 text-xs text-white btn-glow">
                        <i data-lucide="download-cloud" class="w-4 h-4"></i> Fetch Data
                    </button>
                    <button onclick="openVideoDownloadModal()" class="bg-gradient-to-r from-emerald-600 via-teal-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 px-5 rounded-xl font-bold shadow-lg shadow-emerald-900/40 flex items-center gap-2 transition-all active:scale-95 text-xs text-white btn-glow">
                        <i data-lucide="film" class="w-4 h-4"></i> Download Video
                    </button>
                </div>
            </div>

            <div id="settingsPanel" class="hidden grid grid-cols-1 md:grid-cols-3 gap-5 opacity-0 translate-y-4 transition-all duration-500">
                <!-- Video Preview & Quick Controls -->
                <div class="col-span-1 bg-gray-900/80 rounded-xl overflow-hidden border border-gray-700/50 shadow-xl flex flex-col">
                    <iframe id="videoPlayer" class="w-full aspect-video pointer-events-auto" src="" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
                    
                    <!-- Video Playback Controls Bar -->
                    <div class="px-3 py-2 bg-gray-950/80 border-b border-gray-800 flex justify-between items-center text-[10px] text-slate-300">
                        <span class="font-semibold text-purple-300 flex items-center gap-1"><i data-lucide="play-circle" class="w-3 h-3"></i> Seek:</span>
                        <div class="flex gap-1">
                            <button onclick="seekRelative(-10)" class="bg-gray-800 hover:bg-gray-700 px-2 py-0.5 rounded border border-gray-700">-10s</button>
                            <button onclick="seekRelative(10)" class="bg-gray-800 hover:bg-gray-700 px-2 py-0.5 rounded border border-gray-700">+10s</button>
                        </div>
                    </div>

                    <div class="p-4 bg-gray-850/50 flex-1 flex flex-col justify-between">
                        <div>
                            <h3 id="vidTitle" class="font-bold text-sm line-clamp-2 mb-1 text-slate-100" title="Title">Title</h3>
                            <p id="vidAuthor" class="text-xs text-purple-400 font-medium">Channel</p>
                        </div>
                        <div class="mt-4 flex gap-2">
                            <button onclick="switchTab('summary')" class="flex-1 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 text-purple-300 py-1.5 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors">
                                <i data-lucide="sparkles" class="w-3.5 h-3.5"></i> View Summary
                            </button>
                            <button onclick="switchTab('transcript')" class="flex-1 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 text-blue-300 py-1.5 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors">
                                <i data-lucide="file-text" class="w-3.5 h-3.5"></i> Transcript
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Advanced Settings -->
                <div class="col-span-2 bg-gray-900/60 p-5 rounded-xl border border-gray-700/50 flex flex-col justify-between shadow-xl">
                    <div>
                        <h3 class="text-xs font-bold text-slate-300 uppercase tracking-widest border-b border-gray-700/50 pb-2 mb-3 flex items-center gap-2">
                            <i data-lucide="settings-2" class="w-4 h-4 text-purple-400"></i> Extraction Settings
                        </h3>
                        
                        <div class="grid grid-cols-2 gap-4">
                            <div class="bg-gray-850/50 p-3 rounded-lg border border-gray-700/30">
                                <label class="block text-xs text-slate-400 mb-2 flex items-center gap-2"><i data-lucide="scissors" class="w-3 h-3 text-purple-400"></i> Trim Video Range(s)</label>
                                <div class="flex gap-2">
                                    <input type="text" id="timeStart" placeholder="Start (00:00)" style="user-select: text;" class="w-1/2 bg-gray-900 rounded p-2 text-xs border border-gray-700 focus:border-purple-500 outline-none text-slate-200 font-mono">
                                    <span class="text-slate-500 self-center">-</span>
                                    <input type="text" id="timeEnd" placeholder="End (10:00)" style="user-select: text;" class="w-1/2 bg-gray-900 rounded p-2 text-xs border border-gray-700 focus:border-purple-500 outline-none text-slate-200 font-mono">
                                </div>
                            </div>
                            
                            <div class="bg-gray-850/50 p-3 rounded-lg border border-gray-700/30">
                                <label class="block text-xs text-slate-400 mb-2 flex items-center gap-2"><i data-lucide="activity" class="w-3 h-3 text-blue-400"></i> Capture Mode</label>
                                <select id="slideRate" class="w-full bg-gray-900 rounded p-2 text-xs border border-gray-700 focus:border-purple-500 outline-none text-slate-200">
                                    <option value="smart" selected>🤖 Smart Detect (Scene Change)</option>
                                    <option value="30">⏱️ Auto: Every 30s</option>
                                    <option value="10">⏱️ Auto: Every 10s</option>
                                    <option value="5">⏱️ Auto: Every 5s</option>
                                </select>
                            </div>

                            <div class="bg-gray-850/50 p-3 rounded-lg border border-gray-700/30">
                                <label class="block text-xs text-slate-400 mb-2 flex justify-between">
                                    <span><i data-lucide="sliders" class="w-3 h-3 inline mr-1 text-emerald-400"></i> AI Sensitivity</span>
                                    <span id="sensValue" class="text-purple-400 font-mono">0.15</span>
                                </label>
                                <input type="range" id="sensitivity" min="0.05" max="0.30" step="0.05" value="0.15" class="w-full accent-purple-500" oninput="document.getElementById('sensValue').innerText = this.value">
                            </div>

                            <div class="bg-gray-850/50 p-3 rounded-lg border border-gray-700/30 flex flex-col justify-center">
                                <label class="block text-xs text-slate-400 mb-1"><i data-lucide="brain" class="w-3 h-3 inline mr-1 text-pink-400"></i> Mindmap & Quiz</label>
                                <p class="text-[11px] text-slate-400">Auto-generates topic mindmaps & interactive video quizzes.</p>
                            </div>
                        </div>
                    </div>

                    <button id="extractBtn" onclick="startExtraction()" class="mt-4 w-full bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 py-3 rounded-xl font-bold shadow-lg shadow-emerald-900/30 transition-all hover:-translate-y-0.5 active:translate-y-0 flex justify-center items-center gap-2 text-white btn-glow text-xs">
                        <i data-lucide="zap" class="w-4 h-4"></i> Start Smart Extraction
                    </button>
                </div>

                <!-- Direct Media Downloads Card -->
                <div class="col-span-full bg-gray-900/80 p-4 rounded-xl border border-gray-700/50 shadow-xl space-y-3">
                    <div class="flex justify-between items-center border-b border-gray-700/40 pb-2">
                        <h3 class="text-xs font-bold text-slate-200 uppercase tracking-widest flex items-center gap-2">
                            <i data-lucide="download" class="w-4 h-4 text-emerald-400"></i> Direct Media & Subtitle Downloads
                        </h3>
                        <span class="text-[10px] bg-slate-800 text-purple-300 border border-purple-500/30 px-2 py-0.5 rounded font-mono">yt-dlp Engine</span>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <!-- Video Download Box -->
                        <div class="bg-gray-850 p-3 rounded-xl border border-gray-700/60 flex flex-col justify-between gap-2.5 hover:border-blue-500/50 transition-all shadow-md">
                            <div class="flex justify-between items-center gap-2">
                                <span class="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                                    <i data-lucide="film" class="w-4 h-4 text-blue-400"></i> MP4 Video
                                </span>
                                <select id="videoQualitySelect" class="bg-gray-900 text-xs border border-gray-700 rounded-lg px-2 py-1 text-slate-200 focus:border-blue-500 outline-none font-semibold cursor-pointer">
                                    <option value="2160p">🌟 4K (2160p)</option>
                                    <option value="1440p">🌟 2K (1440p)</option>
                                    <option value="1080p">✨ 1080p Full HD</option>
                                    <option value="720p" selected>⚡ 720p HD</option>
                                    <option value="480p">📱 480p SD</option>
                                    <option value="360p">💾 360p Low</option>
                                </select>
                            </div>
                            <button onclick="downloadMedia('video', document.getElementById('videoQualitySelect').value)" class="w-full bg-blue-600/20 hover:bg-blue-600 text-blue-300 hover:text-white border border-blue-500/40 py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-all active:scale-95 shadow">
                                <i data-lucide="download" class="w-3.5 h-3.5"></i> Download MP4 Video
                            </button>
                        </div>

                        <!-- Audio Download Box -->
                        <div class="bg-gray-850 p-3 rounded-xl border border-gray-700/60 flex flex-col justify-between gap-2.5 hover:border-purple-500/50 transition-all shadow-md">
                            <div class="flex justify-between items-center gap-2">
                                <span class="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                                    <i data-lucide="music" class="w-4 h-4 text-purple-400"></i> MP3 Audio
                                </span>
                                <select id="audioQualitySelect" class="bg-gray-900 text-xs border border-gray-700 rounded-lg px-2 py-1 text-slate-200 focus:border-purple-500 outline-none font-semibold cursor-pointer">
                                    <option value="320k">🎧 320 kbps (Best)</option>
                                    <option value="256k">🎵 256 kbps (High)</option>
                                    <option value="192k" selected>🔊 192 kbps (Std)</option>
                                    <option value="128k">📻 128 kbps (Light)</option>
                                </select>
                            </div>
                            <button onclick="downloadMedia('audio', document.getElementById('audioQualitySelect').value)" class="w-full bg-purple-600/20 hover:bg-purple-600 text-purple-300 hover:text-white border border-purple-500/40 py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-all active:scale-95 shadow">
                                <i data-lucide="download" class="w-3.5 h-3.5"></i> Download MP3 Audio
                            </button>
                        </div>

                        <!-- Subtitles Download Box -->
                        <div class="bg-gray-850 p-3 rounded-xl border border-gray-700/60 flex flex-col justify-between gap-2.5 hover:border-emerald-500/50 transition-all shadow-md">
                            <div class="flex justify-between items-center gap-2">
                                <span class="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                                    <i data-lucide="subtitles" class="w-4 h-4 text-emerald-400"></i> SRT Subtitles
                                </span>
                                <span class="text-[10px] text-slate-400 font-mono bg-gray-900 px-2 py-1 rounded border border-gray-700">Auto-SRT</span>
                            </div>
                            <button onclick="downloadMedia('subtitles')" class="w-full bg-emerald-600/20 hover:bg-emerald-600 text-emerald-300 hover:text-white border border-emerald-500/40 py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-all active:scale-95 shadow">
                                <i data-lucide="download" class="w-3.5 h-3.5"></i> Download SRT Subtitles
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            
            <div id="emptyState" class="flex flex-col items-center justify-center py-20 opacity-60">
                <i data-lucide="monitor-play" class="w-20 h-20 text-slate-600 mb-3"></i>
                <p class="text-slate-400 font-medium text-sm">Paste a YouTube link above to fetch video details & summary</p>
            </div>
        </div>

        <!-- TAB 2: AI SUMMARY & QUIZ -->
        <div id="view-summary" class="flex-1 overflow-y-auto no-drag hidden space-y-5 pr-1">
            <!-- Action bar -->
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-gray-900/50 p-3.5 rounded-xl border border-gray-700/40 gap-3">
                <h2 class="font-bold text-base text-slate-100 flex items-center gap-2">
                    <i data-lucide="sparkles" class="w-5 h-5 text-purple-400"></i> Video Summary, Mindmap & Q&A
                </h2>
                <div class="flex items-center gap-2 w-full sm:w-auto">
                    <select id="summaryEngineSelect" class="bg-gray-800 text-xs px-3 py-2 rounded-lg border border-gray-700 outline-none font-semibold text-slate-200 focus:border-purple-500 cursor-pointer" title="Select Summary Engine">
                        <option value="auto" selected>⚡ Auto (Free Fast NLP / AI)</option>
                        <option value="offline">⚡ Free Offline Engine (No API Key Required)</option>
                        <option value="gemini">🤖 Gemini AI Engine</option>
                    </select>
                    <button onclick="loadSummary()" id="genSummaryBtn" class="bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs px-4 py-2 rounded-lg font-bold shadow-md shadow-purple-900/40 flex items-center gap-2 transition-all btn-glow shrink-0">
                        <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Generate Summary
                    </button>
                </div>
            </div>

            <!-- Summary Content Display -->
            <div id="summaryDisplay" class="space-y-5">
                <div class="bg-gray-900/50 p-10 rounded-xl border border-gray-700/40 text-center opacity-60">
                    <i data-lucide="sparkles" class="w-12 h-12 text-purple-400 mx-auto mb-3"></i>
                    <p class="text-sm text-slate-300">Click "Generate / Refresh Summary" above to analyze video content, mindmaps & quiz.</p>
                </div>
            </div>

            <!-- Video Q&A Section -->
            <div class="bg-gray-900/70 p-5 rounded-xl border border-gray-700/50 shadow-xl space-y-4">
                <h3 class="font-bold text-sm text-slate-200 flex items-center gap-2 border-b border-gray-700/40 pb-2">
                    <i data-lucide="message-square" class="w-4 h-4 text-blue-400"></i> Ask Questions About Video
                </h3>
                <div class="flex gap-3">
                    <input type="text" id="askInput" placeholder="Ask anything (e.g., 'What is explained at minute 3?' or 'Summarize main takeaway')" style="user-select: text;"
                           class="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-2.5 text-xs text-slate-100 outline-none focus:border-purple-500 font-sans">
                    <button onclick="askQuestion()" id="askBtn" class="bg-purple-600 hover:bg-purple-500 px-5 py-2.5 rounded-xl text-xs font-bold text-white shadow-md flex items-center gap-1.5 transition-all">
                        <i data-lucide="send" class="w-3.5 h-3.5"></i> Ask
                    </button>
                </div>
                <div id="qaResponse" class="hidden bg-gray-800/60 p-4 rounded-xl border border-gray-700/30 text-xs text-slate-200 whitespace-pre-line leading-relaxed"></div>
            </div>
        </div>

        <!-- TAB 3: INTERACTIVE TRANSCRIPT -->
        <div id="view-transcript" class="flex-1 overflow-y-auto no-drag hidden space-y-4 pr-1">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 bg-gray-900/60 p-4 rounded-xl border border-gray-700/50">
                <div class="relative flex-1 w-full">
                    <i data-lucide="search" class="absolute left-3.5 top-3 text-slate-400 w-4 h-4"></i>
                    <input type="text" id="transcriptSearch" oninput="filterTranscript()" placeholder="Search transcript keywords..." style="user-select: text;"
                           class="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2 text-xs text-slate-100 outline-none focus:border-purple-500">
                </div>
                <div class="flex gap-2 w-full sm:w-auto">
                    <button onclick="copyTranscript()" class="bg-gray-800 hover:bg-gray-700 text-slate-200 border border-gray-700 px-3 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5">
                        <i data-lucide="copy" class="w-3.5 h-3.5"></i> Copy Text
                    </button>
                    <button onclick="downloadTranscript()" class="bg-purple-600 hover:bg-purple-500 text-white px-3 py-2 rounded-lg text-xs font-semibold flex items-center gap-1.5">
                        <i data-lucide="download" class="w-3.5 h-3.5"></i> Save .TXT
                    </button>
                </div>
            </div>

            <div id="transcriptList" class="space-y-2 pr-1">
                <div class="text-center py-12 opacity-50 text-slate-400">
                    <i data-lucide="file-text" class="w-12 h-12 mx-auto mb-2 text-slate-500"></i>
                    <p class="text-sm">Load a video URL to view interactive transcript.</p>
                </div>
            </div>
        </div>

        <!-- TAB 4: PRO EDITOR -->
        <div id="view-editor" class="flex-1 overflow-hidden no-drag hidden flex flex-col">
            <div class="flex flex-col md:flex-row justify-between items-start md:items-end mb-3 bg-gray-900/60 p-3.5 rounded-xl border border-gray-700/50 shadow-sm gap-3">
                <div class="space-y-1">
                    <h2 class="font-bold text-lg flex items-center gap-2">
                        Slide Editor <span id="slideCount" class="bg-purple-500/20 text-purple-400 text-xs px-2.5 py-0.5 rounded-full font-mono"></span>
                    </h2>
                    <div class="flex gap-2 text-xs">
                        <button onclick="filterEditorView('all')" id="btnFilterAll" class="text-purple-400 font-bold hover:underline">All</button>
                        <span class="text-slate-600">•</span>
                        <button onclick="filterEditorView('starred')" id="btnFilterStarred" class="text-slate-400 font-semibold hover:underline">⭐ Starred</button>
                    </div>
                </div>
                <div class="flex gap-2 items-center flex-wrap">
                    <button onclick="openFlashcards()" class="bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border border-indigo-500/40 px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors">
                        <i data-lucide="layers" class="w-3.5 h-3.5"></i> 🃏 Study Flashcards
                    </button>
                    <label class="flex items-center gap-1.5 text-xs font-semibold bg-gray-800 px-2.5 py-1.5 rounded-lg cursor-pointer hover:bg-gray-700 border border-gray-700 transition-colors">
                        <input type="checkbox" id="enhanceToggle" onchange="renderEditor()" class="accent-purple-500 w-3.5 h-3.5"> 
                        <i data-lucide="sparkles" class="w-3.5 h-3.5 text-emerald-400"></i> Sharpen Text
                    </label>
                    <label class="flex items-center gap-1.5 text-xs font-semibold bg-gray-800 px-2.5 py-1.5 rounded-lg cursor-pointer hover:bg-gray-700 border border-gray-700 transition-colors">
                        <input type="checkbox" id="invertToggle" onchange="toggleInvert()" class="accent-purple-500 w-3.5 h-3.5"> 
                        <i data-lucide="moon" class="w-3.5 h-3.5 text-purple-400"></i> Invert
                    </label>
                    <select id="exportLayout" class="bg-gray-800 text-xs px-2.5 py-1.5 rounded-lg border border-gray-700 outline-none font-semibold hover:border-purple-500 transition-colors cursor-pointer text-slate-200" title="Slide layout per page">
                        <option value="1">📄 1 Slide / Page</option>
                        <option value="2">📑 2 Slides / Page</option>
                        <option value="4">🗂️ 4 Slides / Page</option>
                    </select>
                    <select id="exportQuality" class="bg-gray-800 text-xs px-2.5 py-1.5 rounded-lg border border-gray-700 outline-none font-semibold hover:border-purple-500 transition-colors cursor-pointer text-slate-200" title="PDF & Image Export Quality">
                        <option value="high" selected>💎 High Quality (100%)</option>
                        <option value="medium">⚡ Balanced (80%)</option>
                        <option value="compact">📦 Compact (60%)</option>
                    </select>
                </div>
            </div>
            
            <!-- Grid Scrollable Area -->
            <div class="flex-1 overflow-y-auto pr-2 pb-2">
                <div id="editorGrid" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 content-start"></div>
            </div>

            <!-- Export Buttons -->
            <div class="flex gap-2.5 pt-3 border-t border-white/10 mt-2 justify-end flex-wrap bg-slate-900/50 p-2 rounded-b-xl">
                <button onclick="clearAllSlides()" class="mr-auto text-red-400 hover:text-red-300 text-xs font-semibold flex items-center gap-1 px-2"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i> Clear All</button>
                
                <button onclick="exportFiles('zip')" class="bg-gray-800 hover:bg-gray-700 border border-gray-700 text-slate-200 px-4 py-2 rounded-lg font-bold text-xs flex items-center gap-1.5 transition-colors">
                    <i data-lucide="archive" class="w-3.5 h-3.5"></i> ZIP
                </button>
                <button onclick="exportFiles('txt')" class="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg font-bold text-xs shadow-md flex items-center gap-1.5 transition-colors">
                    <i data-lucide="scan-text" class="w-3.5 h-3.5"></i> OCR Text
                </button>
                <button onclick="exportFiles('md')" class="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg font-bold text-xs shadow-md flex items-center gap-1.5 transition-colors">
                    <i data-lucide="file-code" class="w-3.5 h-3.5"></i> Study Notes (.MD)
                </button>
                <button onclick="exportFiles('pptx')" class="bg-orange-600 hover:bg-orange-500 text-white px-4 py-2 rounded-lg font-bold text-xs shadow-md flex items-center gap-1.5 transition-colors">
                    <i data-lucide="presentation" class="w-3.5 h-3.5"></i> PPTX
                </button>
                <button onclick="exportFiles('pdf')" class="bg-purple-600 hover:bg-purple-500 text-white px-5 py-2 rounded-lg font-bold text-xs shadow-md flex items-center gap-1.5 transition-transform hover:scale-105 active:scale-95 btn-glow">
                    <i data-lucide="file-text" class="w-3.5 h-3.5"></i> Save PDF
                </button>
            </div>
        </div>

        <!-- TAB 5: HISTORY -->
        <div id="view-history" class="flex-1 overflow-y-auto no-drag hidden pr-1">
            <h2 class="text-xl font-bold mb-4 flex items-center gap-2 border-b border-gray-700 pb-2"><i data-lucide="clock" class="w-5 h-5 text-purple-400"></i> Recent Extractions</h2>
            <div id="historyList" class="space-y-3 pr-2"></div>
        </div>
    </div>

    <!-- LIGHTBOX SLIDE ZOOM MODAL -->
    <div id="lightboxModal" class="hidden fixed inset-0 z-50 bg-black/90 backdrop-blur-md flex items-center justify-center p-4">
        <div class="relative max-w-5xl w-full flex flex-col items-center">
            <button onclick="closeLightbox()" class="absolute -top-12 right-0 text-white hover:text-purple-400 text-sm font-bold flex items-center gap-1">
                <i data-lucide="x" class="w-6 h-6"></i> Close (Esc)
            </button>
            <div class="relative w-full max-h-[75vh] flex justify-center bg-gray-950 rounded-xl overflow-hidden border border-gray-800 shadow-2xl">
                <img id="lightboxImg" src="" class="max-h-[75vh] object-contain">
                <button onclick="prevLightbox()" class="absolute left-4 top-1/2 -translate-y-1/2 bg-black/60 hover:bg-purple-600 text-white p-3 rounded-full transition-all">
                    <i data-lucide="chevron-left" class="w-6 h-6"></i>
                </button>
                <button onclick="nextLightbox()" class="absolute right-4 top-1/2 -translate-y-1/2 bg-black/60 hover:bg-purple-600 text-white p-3 rounded-full transition-all">
                    <i data-lucide="chevron-right" class="w-6 h-6"></i>
                </button>
            </div>
            <div class="mt-3 text-center text-xs text-slate-300 font-mono" id="lightboxTitle"></div>
        </div>
    </div>

    <!-- STUDY FLASHCARDS MODAL WITH SELF-TESTING SCORE -->
    <div id="flashcardModal" class="hidden fixed inset-0 z-50 bg-black/90 backdrop-blur-md flex items-center justify-center p-4">
        <div class="relative max-w-xl w-full flex flex-col items-center space-y-4">
            <button onclick="closeFlashcards()" class="absolute -top-10 right-0 text-white hover:text-purple-400 text-sm font-bold flex items-center gap-1">
                <i data-lucide="x" class="w-6 h-6"></i> Close (Esc)
            </button>

            <div class="flex justify-between items-center w-full px-2 text-xs text-purple-300 font-mono font-semibold">
                <span id="flashcardCounter">Card 1 of 5</span>
                <span id="flashcardScore">Score: 0/0 (0%)</span>
            </div>

            <!-- 3D Flip Card Container -->
            <div onclick="flipFlashcard()" class="w-full h-80 cursor-pointer perspective-1000">
                <div id="flashcardInner" class="w-full h-full relative duration-500 transition-transform transform-style-3d shadow-2xl rounded-2xl border border-purple-500/40 bg-gray-900">
                    <!-- Front Side -->
                    <div class="absolute inset-0 backface-hidden p-4 flex flex-col justify-between items-center bg-gray-900 rounded-2xl border border-gray-800">
                        <span class="text-[11px] text-purple-400 font-semibold uppercase tracking-widest">Front: Slide Image (Click to Flip 🔄)</span>
                        <img id="flashcardImg" src="" class="max-h-56 object-contain rounded-lg">
                        <span class="text-xs text-slate-400">Click card to reveal notes</span>
                    </div>
                    <!-- Back Side -->
                    <div class="absolute inset-0 backface-hidden rotate-y-180 p-6 flex flex-col justify-between bg-gradient-to-br from-gray-900 via-purple-950/50 to-gray-900 rounded-2xl border border-purple-500/50">
                        <span class="text-[11px] text-purple-400 font-semibold uppercase tracking-widest">Back: Custom Note / Key Concept</span>
                        <div id="flashcardNote" class="text-sm text-slate-100 leading-relaxed font-sans flex-1 flex items-center justify-center text-center p-4"></div>
                        <span class="text-xs text-slate-400 text-center">Click to flip back</span>
                    </div>
                </div>
            </div>

            <div class="flex items-center gap-3 w-full justify-between">
                <button onclick="prevFlashcard()" class="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-xl text-xs font-bold border border-gray-700">← Previous</button>
                <div class="flex gap-2">
                    <button onclick="scoreFlashcard(false)" class="bg-red-900/40 hover:bg-red-800/60 text-red-200 border border-red-500/40 px-3 py-1.5 rounded-lg text-xs font-semibold">❌ Need Revision</button>
                    <button onclick="scoreFlashcard(true)" class="bg-emerald-900/40 hover:bg-emerald-800/60 text-emerald-200 border border-emerald-500/40 px-3 py-1.5 rounded-lg text-xs font-semibold">✅ Got It Right</button>
                </div>
                <button onclick="nextFlashcard()" class="bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-lg">Next →</button>
            </div>
        </div>
    </div>

    <!-- KEYBOARD HOTKEYS OVERLAY MODAL -->
    <div id="hotkeyModal" class="hidden fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-4">
        <div class="bg-gray-900 p-6 rounded-2xl border border-purple-500/40 max-w-md w-full space-y-4 relative shadow-2xl">
            <button onclick="closeHotkeyModal()" class="absolute top-4 right-4 text-slate-400 hover:text-white"><i data-lucide="x" class="w-5 h-5"></i></button>
            <h3 class="text-sm font-bold text-slate-100 uppercase tracking-widest flex items-center gap-2 border-b border-gray-800 pb-2">
                <i data-lucide="keyboard" class="w-4 h-4 text-purple-400"></i> Keyboard Shortcuts Cheat Sheet
            </h3>
            <div class="space-y-2 text-xs text-slate-300">
                <div class="flex justify-between py-1 border-b border-gray-800/50"><span class="font-mono bg-gray-800 px-2 py-0.5 rounded text-purple-300">?</span><span>Toggle Hotkeys Overlay</span></div>
                <div class="flex justify-between py-1 border-b border-gray-800/50"><span class="font-mono bg-gray-800 px-2 py-0.5 rounded text-purple-300">Space</span><span>Flip Flashcard</span></div>
                <div class="flex justify-between py-1 border-b border-gray-800/50"><span class="font-mono bg-gray-800 px-2 py-0.5 rounded text-purple-300">← / →</span><span>Navigate Lightbox / Flashcards</span></div>
                <div class="flex justify-between py-1 border-b border-gray-800/50"><span class="font-mono bg-gray-800 px-2 py-0.5 rounded text-purple-300">Esc</span><span>Close Active Modal</span></div>
            </div>
        </div>
    </div>

    <script>
        lucide.createIcons();

        let currentTaskId = "";
        let currentTitle = "";
        let slidesArray = [];
        let slideNotesMap = {};
        let slideTagsMap = {};
        let starredSlidesMap = {};
        let currentEditorFilter = 'all';
        let rawTranscriptData = [];
        let currentLightboxIndex = 0;
        let currentFlashcardIndex = 0;
        let flashcardRightCount = 0;
        let flashcardTotalAttempted = 0;
        let isFlashcardFlipped = false;
        let currentExecutiveSummaryText = "";
        let currentUtterance = null;

        function setThemeAccent(theme) {
            const root = document.documentElement;
            if(theme === 'purple') {
                root.style.setProperty('--primary-accent', '#a855f7');
                root.style.setProperty('--primary-glow', 'rgba(168, 85, 247, 0.4)');
            } else if(theme === 'cyan') {
                root.style.setProperty('--primary-accent', '#06b6d4');
                root.style.setProperty('--primary-glow', 'rgba(6, 182, 212, 0.4)');
            } else if(theme === 'emerald') {
                root.style.setProperty('--primary-accent', '#10b981');
                root.style.setProperty('--primary-glow', 'rgba(16, 185, 129, 0.4)');
            } else if(theme === 'rose') {
                root.style.setProperty('--primary-accent', '#f43f5e');
                root.style.setProperty('--primary-glow', 'rgba(244, 63, 94, 0.4)');
            }
            Toast(`Theme changed to ${theme.toUpperCase()}`, "info");
        }

        function switchTab(tabId) {
            ['extract', 'summary', 'transcript', 'editor', 'history'].forEach(t => {
                const el = document.getElementById(`view-${t}`);
                if(el) el.classList.add('hidden');
                const btn = document.getElementById(`tab-${t}`);
                if(btn) btn.classList.remove('active');
            });
            const targetView = document.getElementById(`view-${tabId}`);
            if(targetView) targetView.classList.remove('hidden');
            const targetBtn = document.getElementById(`tab-${tabId}`);
            if(targetBtn) targetBtn.classList.add('active');

            if(tabId === 'history') loadHistory();
            if(tabId === 'transcript' && rawTranscriptData.length === 0) fetchTranscriptData();
        }

        function Toast(msg, icon="info") {
            Swal.fire({
                toast: true, position: 'bottom-end', showConfirmButton: false, timer: 3000,
                timerProgressBar: true, icon: icon, title: msg,
                background: '#172033', color: '#fff', iconColor: 'var(--primary-accent)'
            });
        }

        function openHotkeyModal() { document.getElementById('hotkeyModal').classList.remove('hidden'); }
        function closeHotkeyModal() { document.getElementById('hotkeyModal').classList.add('hidden'); }

        function getYTId(url) {
            const match = url.match(/^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/);
            return (match && match[2].length === 11) ? match[2] : null;
        }

        function seekToTime(sec) {
            const url = document.getElementById('urlInput').value;
            const vidId = getYTId(url);
            if(vidId) {
                document.getElementById('videoPlayer').src = `https://www.youtube.com/embed/${vidId}?start=${Math.floor(sec)}&autoplay=1`;
                Toast(`Jumping to ${sec}s in video`, "info");
                switchTab('extract');
            }
        }

        function seekRelative(deltaSec) {
            const player = document.getElementById('videoPlayer');
            const src = player.src;
            const match = src.match(/start=(\d+)/);
            let currentSec = match ? parseInt(match[1]) : 0;
            let targetSec = Math.max(0, currentSec + deltaSec);
            seekToTime(targetSec);
        }

        async function downloadMedia(type, quality = '') {
            const url = document.getElementById('urlInput').value;
            if(!url) return Toast("Please enter a YouTube link first!", "warning");

            if(!quality) {
                if(type === 'video') quality = document.getElementById('videoQualitySelect')?.value || '720p';
                else if(type === 'audio') quality = document.getElementById('audioQualitySelect')?.value || '192k';
                else quality = 'default';
            }
            
            Toast(`Downloading ${type.toUpperCase()} (${quality})... Please wait`, "info");
            const downloadUrl = `/api/download_media?url=${encodeURIComponent(url)}&type=${type}&quality=${quality}`;
            
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.target = '_blank';
            document.body.appendChild(a);
            a.click();
            a.remove();
        }

        function openVideoDownloadModal() {
            const url = document.getElementById('urlInput').value;
            if(!url) return Toast("Please enter a YouTube link first!", "warning");

            Swal.fire({
                title: '🎬 Select Download Quality',
                html: `
                    <div class="space-y-4 text-left font-sans text-slate-200 pt-2">
                        <div>
                            <label class="block text-xs font-bold text-slate-400 mb-2 uppercase tracking-wider">🎥 MP4 Video Resolution Quality:</label>
                            <div class="grid grid-cols-3 gap-2 text-xs">
                                <button onclick="downloadMedia('video', '2160p');Swal.close();" class="bg-gray-800 hover:bg-emerald-600 hover:text-white p-2.5 rounded-xl border border-gray-700 flex flex-col items-center gap-0.5 transition-all">
                                    <span class="font-bold text-amber-400">4K (2160p)</span>
                                    <span class="text-[10px] opacity-75">Ultra HD</span>
                                </button>
                                <button onclick="downloadMedia('video', '1440p');Swal.close();" class="bg-gray-800 hover:bg-emerald-600 hover:text-white p-2.5 rounded-xl border border-gray-700 flex flex-col items-center gap-0.5 transition-all">
                                    <span class="font-bold text-cyan-400">2K (1440p)</span>
                                    <span class="text-[10px] opacity-75">Quad HD</span>
                                </button>
                                <button onclick="downloadMedia('video', '1080p');Swal.close();" class="bg-gray-800 hover:bg-emerald-600 hover:text-white p-2.5 rounded-xl border border-gray-700 flex flex-col items-center gap-0.5 transition-all">
                                    <span class="font-bold text-purple-400">1080p</span>
                                    <span class="text-[10px] opacity-75">Full HD</span>
                                </button>
                                <button onclick="downloadMedia('video', '720p');Swal.close();" class="bg-gray-800 hover:bg-emerald-600 hover:text-white p-2.5 rounded-xl border border-gray-700 flex flex-col items-center gap-0.5 transition-all">
                                    <span class="font-bold text-emerald-400">720p</span>
                                    <span class="text-[10px] opacity-75">HD Recommended</span>
                                </button>
                                <button onclick="downloadMedia('video', '480p');Swal.close();" class="bg-gray-800 hover:bg-emerald-600 hover:text-white p-2.5 rounded-xl border border-gray-700 flex flex-col items-center gap-0.5 transition-all">
                                    <span class="font-bold text-blue-400">480p</span>
                                    <span class="text-[10px] opacity-75">Standard SD</span>
                                </button>
                                <button onclick="downloadMedia('video', '360p');Swal.close();" class="bg-gray-800 hover:bg-emerald-600 hover:text-white p-2.5 rounded-xl border border-gray-700 flex flex-col items-center gap-0.5 transition-all">
                                    <span class="font-bold text-slate-300">360p</span>
                                    <span class="text-[10px] opacity-75">Data Saver</span>
                                </button>
                            </div>
                        </div>

                        <div class="border-t border-gray-700/60 pt-3">
                            <label class="block text-xs font-bold text-slate-400 mb-2 uppercase tracking-wider">🎵 MP3 Audio Bitrate Quality:</label>
                            <div class="grid grid-cols-4 gap-2 text-xs">
                                <button onclick="downloadMedia('audio', '320k');Swal.close();" class="bg-gray-800 hover:bg-purple-600 hover:text-white p-2 rounded-xl border border-gray-700 text-center transition-all">
                                    <div class="font-bold text-purple-300 text-xs">320 kbps</div>
                                    <div class="text-[9px] opacity-70">Best</div>
                                </button>
                                <button onclick="downloadMedia('audio', '256k');Swal.close();" class="bg-gray-800 hover:bg-purple-600 hover:text-white p-2 rounded-xl border border-gray-700 text-center transition-all">
                                    <div class="font-bold text-purple-300 text-xs">256 kbps</div>
                                    <div class="text-[9px] opacity-70">High</div>
                                </button>
                                <button onclick="downloadMedia('audio', '192k');Swal.close();" class="bg-gray-800 hover:bg-purple-600 hover:text-white p-2 rounded-xl border border-gray-700 text-center transition-all">
                                    <div class="font-bold text-purple-300 text-xs">192 kbps</div>
                                    <div class="text-[9px] opacity-70">Standard</div>
                                </button>
                                <button onclick="downloadMedia('audio', '128k');Swal.close();" class="bg-gray-800 hover:bg-purple-600 hover:text-white p-2 rounded-xl border border-gray-700 text-center transition-all">
                                    <div class="font-bold text-purple-300 text-xs">128 kbps</div>
                                    <div class="text-[9px] opacity-70">Light</div>
                                </button>
                            </div>
                        </div>

                        <div class="border-t border-gray-700/60 pt-3 flex justify-between items-center text-xs">
                            <span class="text-slate-400">📜 Need Subtitles?</span>
                            <button onclick="downloadMedia('subtitles');Swal.close();" class="bg-emerald-600/20 hover:bg-emerald-600 text-emerald-300 hover:text-white px-3 py-1.5 rounded-lg border border-emerald-500/40 font-semibold transition-all">
                                Download SRT Subtitles
                            </button>
                        </div>
                    </div>
                `,
                showConfirmButton: false,
                showCancelButton: true,
                cancelButtonText: 'Cancel',
                background: '#172033',
                color: '#fff',
                customClass: {
                    popup: 'rounded-2xl border border-gray-700 shadow-2xl max-w-lg'
                }
            });
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
                    
                    rawTranscriptData = [];
                    Toast("Video loaded successfully!", "success");
                } else {
                    Swal.fire({ title: 'Error!', text: data.detail, icon: 'error', background: '#172033', color: '#fff' });
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
            btn.innerHTML = '<div class="loader"></div> Extracting... (Please wait)';
            btn.disabled = true;

            Swal.fire({
                title: 'Extracting Slides...',
                html: 'Processing video frames. Please stay on this tab.',
                allowOutsideClick: false, background: '#172033', color: '#fff',
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
                    if(slidesArray.length === 0) {
                        Swal.fire({
                            title: 'No Slides Detected',
                            text: 'No distinct slide changes were detected in this video. You can download the full video, MP3 audio, or subtitles directly below!',
                            icon: 'info',
                            showCancelButton: true,
                            confirmButtonText: 'Download MP3 Audio',
                            cancelButtonText: 'Close',
                            background: '#172033', color: '#fff', confirmButtonColor: 'var(--primary-accent)'
                        }).then((r) => { if(r.isConfirmed) downloadMedia('audio'); });
                    } else {
                        Toast("Extraction Complete!", "success");
                    }
                } else {
                    Swal.fire({ title: 'Extraction Failed', text: data.detail, icon: 'error', background: '#172033', color: '#fff' });
                }
            } catch(e) { 
                Swal.fire({ title: 'Error', text: "Server timed out or crashed.", icon: 'error', background: '#172033', color: '#fff' });
            }
            
            btn.innerHTML = '<i data-lucide="zap" class="w-4 h-4"></i> Start Smart Extraction';
            lucide.createIcons();
            btn.disabled = false;
        }

        async function fetchTranscriptData() {
            const url = document.getElementById('urlInput').value;
            if(!url) return;
            
            const list = document.getElementById('transcriptList');
            list.innerHTML = '<div class="text-center py-10"><div class="loader"></div><p class="text-xs text-slate-400 mt-2">Fetching transcript...</p></div>';
            
            try {
                const res = await fetch(`/api/transcript?url=${encodeURIComponent(url)}`);
                const data = await res.json();
                rawTranscriptData = data.transcript || [];
                renderTranscript(rawTranscriptData);
            } catch(e) {
                list.innerHTML = '<p class="text-red-400 text-center py-6 text-xs">Failed to load transcript.</p>';
            }
        }

        function renderTranscript(items) {
            const list = document.getElementById('transcriptList');
            list.innerHTML = '';
            if(!items || items.length === 0) {
                list.innerHTML = '<p class="text-slate-500 text-center py-10 text-xs">No transcript available for this video.</p>';
                return;
            }
            
            items.forEach(item => {
                const sec = Math.floor(item.start);
                const m = Math.floor(sec / 60);
                const s = sec % 60;
                const timeStr = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
                
                const div = document.createElement('div');
                div.className = 'bg-gray-900/50 hover:bg-gray-800/80 p-2.5 rounded-lg border border-gray-700/30 flex items-start gap-3 transition-colors text-xs cursor-pointer';
                div.onclick = () => seekToTime(item.start);
                div.innerHTML = `
                    <span class="bg-purple-600/20 text-purple-400 hover:bg-purple-600 hover:text-white px-2 py-0.5 rounded font-mono text-[11px] shrink-0 transition-colors">
                        ${timeStr}
                    </span>
                    <span class="text-slate-200 flex-1 leading-relaxed">${item.text}</span>
                `;
                list.appendChild(div);
            });
        }

        function filterTranscript() {
            const q = document.getElementById('transcriptSearch').value.toLowerCase();
            const filtered = rawTranscriptData.filter(i => i.text.toLowerCase().includes(q));
            renderTranscript(filtered);
        }

        function copyTranscript() {
            if(!rawTranscriptData.length) return Toast("No transcript to copy", "warning");
            const fullText = rawTranscriptData.map(i => `[${Math.floor(i.start)}s] ${i.text}`).join('\n');
            navigator.clipboard.writeText(fullText);
            Toast("Transcript copied to clipboard!", "success");
        }

        function downloadTranscript() {
            if(!rawTranscriptData.length) return Toast("No transcript to download", "warning");
            const fullText = rawTranscriptData.map(i => `[${Math.floor(i.start)}s] ${i.text}`).join('\n');
            const blob = new Blob([fullText], { type: 'text/plain' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `${currentTitle || 'Video'}_Transcript.txt`;
            a.click();
            Toast("Downloaded transcript!", "success");
        }

        async function loadSummary() {
            const url = document.getElementById('urlInput').value;
            if(!url) return Toast("Please enter a YouTube video URL first!", "warning");

            const btn = document.getElementById('genSummaryBtn');
            btn.innerHTML = '<div class="loader" style="width:14px;height:14px;"></div> Analyzing...';
            btn.disabled = true;

            const engine = document.getElementById('summaryEngineSelect')?.value || 'auto';
            let apiKeyToUse = "";
            if(engine === 'offline') {
                apiKeyToUse = "OFFLINE";
            }

            const display = document.getElementById('summaryDisplay');
            display.innerHTML = '<div class="bg-gray-900/50 p-10 rounded-xl border border-gray-700/40 text-center"><div class="loader mb-3" style="width:28px;height:28px;"></div><p class="text-xs text-slate-300">Extracting concepts, building mindmap & generating summary...</p></div>';

            try {
                const res = await fetch('/api/summary', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url, title: currentTitle, api_key: apiKeyToUse })
                });
                const data = await res.json();
                
                if(res.ok) {
                    currentExecutiveSummaryText = data.executive_summary || "";
                    renderSummary(data);
                    Toast(`Analysis Complete (${data.source === 'gemini' ? '🤖 Gemini AI' : '⚡ Free Offline NLP'})!`, "success");
                } else {
                    display.innerHTML = `<p class="text-red-400 text-center py-6 text-xs">${data.detail || 'Failed to generate summary'}</p>`;
                }
            } catch(e) {
                display.innerHTML = '<p class="text-red-400 text-center py-6 text-xs">Error connecting to summary service.</p>';
            }

            btn.innerHTML = '<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Refresh Summary';
            lucide.createIcons();
            btn.disabled = false;
        }

        function speakSummary() {
            if(!currentExecutiveSummaryText) return Toast("No summary text to read", "warning");
            stopSummary();
            const rate = parseFloat(document.getElementById('ttsRate').value) || 1.0;
            currentUtterance = new SpeechSynthesisUtterance(currentExecutiveSummaryText);
            currentUtterance.rate = rate;
            window.speechSynthesis.speak(currentUtterance);
            Toast("Reading summary aloud...", "info");
        }

        function pauseSummary() {
            if(window.speechSynthesis.speaking) {
                window.speechSynthesis.pause();
                Toast("Paused audio", "info");
            }
        }

        function stopSummary() {
            window.speechSynthesis.cancel();
        }

        function renderSummary(data) {
            const display = document.getElementById('summaryDisplay');
            display.innerHTML = '';

            const badge = data.source === 'gemini' 
                ? '<span class="bg-purple-900/40 text-purple-300 border border-purple-500/40 px-2.5 py-0.5 rounded-full text-[10px] font-semibold">Gemini AI Engine</span>'
                : '<span class="bg-blue-900/40 text-blue-300 border border-blue-500/40 px-2.5 py-0.5 rounded-full text-[10px] font-semibold">Built-in Smart NLP</span>';

            const statsRibbon = data.stats ? `
                <div class="flex flex-wrap gap-3 bg-gray-950/70 p-3 rounded-xl border border-gray-800 text-xs text-slate-300">
                    <span class="flex items-center gap-1.5 font-semibold text-purple-300"><i data-lucide="clock" class="w-3.5 h-3.5"></i> Reading Time: ~${data.stats.read_time_min} mins</span>
                    <span class="text-slate-600">•</span>
                    <span class="flex items-center gap-1.5"><i data-lucide="align-left" class="w-3.5 h-3.5 text-blue-400"></i> Word Count: ${data.stats.word_count}</span>
                    <span class="text-slate-600">•</span>
                    <span class="flex items-center gap-1.5"><i data-lucide="layers" class="w-3.5 h-3.5 text-emerald-400"></i> Segments: ${data.stats.segments}</span>
                </div>
            ` : '';

            let takeawaysHTML = (data.key_takeaways || []).map(t => 
                `<li class="flex items-start gap-2 text-xs text-slate-200"><i data-lucide="check-circle2" class="w-4 h-4 text-emerald-400 shrink-0 mt-0.5"></i><span>${t}</span></li>`
            ).join('');

            let chaptersHTML = (data.chapters || []).map(c => `
                <div onclick="seekToTime(${c.seconds})" class="bg-gray-800/60 hover:bg-gray-800 p-3 rounded-lg border border-gray-700/40 flex items-center justify-between cursor-pointer transition-all hover:border-purple-500/40">
                    <span class="text-xs font-semibold text-slate-200 line-clamp-1">${c.title}</span>
                    <span class="bg-purple-600/20 text-purple-300 font-mono text-[11px] px-2 py-0.5 rounded shrink-0">${c.time}</span>
                </div>
            `).join('');

            let quizHTML = (data.quiz || []).map((q, qIdx) => `
                <div class="bg-gray-800/60 p-4 rounded-xl border border-gray-700/40 space-y-3">
                    <h4 class="font-bold text-xs text-slate-100 flex items-center gap-2">
                        <span class="bg-purple-600 text-white w-5 h-5 rounded-full text-[11px] flex items-center justify-center font-mono">${qIdx + 1}</span>
                        ${q.question}
                    </h4>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        ${q.options.map((opt, optIdx) => `
                            <button onclick="checkAnswer(${qIdx}, ${optIdx}, ${q.correct}, '${encodeURIComponent(q.explanation)}')" class="quiz-opt-${qIdx}-${optIdx} text-left bg-gray-900/60 hover:bg-gray-700 border border-gray-700 p-2.5 rounded-lg text-xs text-slate-200 transition-colors">
                                ${opt}
                            </button>
                        `).join('')}
                    </div>
                    <div id="quizExp-${qIdx}" class="hidden text-[11px] p-2 rounded bg-purple-900/20 text-purple-200 border border-purple-500/20"></div>
                </div>
            `).join('');

            display.innerHTML = `
                ${statsRibbon}

                <div class="bg-gray-900/70 p-5 rounded-xl border border-gray-700/50 shadow-lg space-y-3">
                    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center border-b border-gray-700/40 pb-2 gap-2">
                        <h3 class="font-bold text-sm text-slate-100 flex items-center gap-2">
                            <i data-lucide="file-text" class="w-4 h-4 text-purple-400"></i> Executive Summary
                        </h3>
                        <div class="flex items-center gap-2">
                            ${badge}
                            <div class="flex items-center gap-1.5 bg-gray-950 border border-gray-800 px-2 py-1 rounded-lg text-[11px]">
                                <button onclick="speakSummary()" class="text-purple-400 hover:text-white font-semibold flex items-center gap-1"><i data-lucide="volume-2" class="w-3.5 h-3.5"></i> Read</button>
                                <button onclick="pauseSummary()" class="text-slate-400 hover:text-white"><i data-lucide="pause" class="w-3 h-3"></i></button>
                                <button onclick="stopSummary()" class="text-slate-400 hover:text-white"><i data-lucide="square" class="w-3 h-3"></i></button>
                                <select id="ttsRate" class="bg-gray-900 text-slate-300 rounded px-1 text-[10px]">
                                    <option value="1">1.0x</option>
                                    <option value="1.25">1.25x</option>
                                    <option value="1.5">1.5x</option>
                                </select>
                            </div>
                        </div>
                    </div>
                    <p class="text-xs text-slate-200 leading-relaxed">${data.executive_summary}</p>
                </div>

                <div class="bg-gray-900/70 p-5 rounded-xl border border-gray-700/50 shadow-lg space-y-3">
                    <h3 class="font-bold text-sm text-slate-100 flex items-center gap-2 border-b border-gray-700/40 pb-2">
                        <i data-lucide="list-checks" class="w-4 h-4 text-emerald-400"></i> Key Takeaways & Core Concepts
                    </h3>
                    <ul class="space-y-2.5">${takeawaysHTML}</ul>
                </div>

                ${data.mindmap ? `
                <div class="bg-gray-900/70 p-5 rounded-xl border border-gray-700/50 shadow-lg space-y-3">
                    <h3 class="font-bold text-sm text-slate-100 flex items-center gap-2 border-b border-gray-700/40 pb-2">
                        <i data-lucide="git-fork" class="w-4 h-4 text-cyan-400"></i> Video Concept Mindmap
                    </h3>
                    <div class="mermaid flex justify-center bg-gray-950/60 p-4 rounded-xl border border-gray-800 overflow-x-auto text-xs">
                        ${data.mindmap}
                    </div>
                </div>` : ''}

                ${quizHTML ? `
                <div class="bg-gray-900/70 p-5 rounded-xl border border-gray-700/50 shadow-lg space-y-4">
                    <h3 class="font-bold text-sm text-slate-100 flex items-center gap-2 border-b border-gray-700/40 pb-2">
                        <i data-lucide="help-circle" class="w-4 h-4 text-pink-400"></i> Interactive Knowledge Check (Quiz)
                    </h3>
                    <div class="space-y-4">${quizHTML}</div>
                </div>` : ''}

                ${chaptersHTML ? `
                <div class="bg-gray-900/70 p-5 rounded-xl border border-gray-700/50 shadow-lg space-y-3">
                    <h3 class="font-bold text-sm text-slate-100 flex items-center gap-2 border-b border-gray-700/40 pb-2">
                        <i data-lucide="clock" class="w-4 h-4 text-blue-400"></i> Timestamped Chapters (Click to Jump)
                    </h3>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">${chaptersHTML}</div>
                </div>` : ''}
            `;
            lucide.createIcons();
            try { mermaid.contentLoaded(); } catch(e) {}
        }

        function checkAnswer(qIdx, selected, correct, expEncoded) {
            const exp = decodeURIComponent(expEncoded);
            const opts = document.querySelectorAll(`[class*="quiz-opt-${qIdx}-"]`);
            opts.forEach((btn, idx) => {
                btn.disabled = true;
                if(idx === correct) {
                    btn.classList.remove('bg-gray-900/60', 'border-gray-700');
                    btn.classList.add('bg-emerald-600/30', 'border-emerald-500', 'text-emerald-200');
                } else if(idx === selected) {
                    btn.classList.remove('bg-gray-900/60', 'border-gray-700');
                    btn.classList.add('bg-red-600/30', 'border-red-500', 'text-red-200');
                }
            });
            const expBox = document.getElementById(`quizExp-${qIdx}`);
            if(expBox) {
                expBox.classList.remove('hidden');
                expBox.innerHTML = `<strong>Explanation:</strong> ${exp}`;
            }
            if(selected === correct) confetti({ particleCount: 40, spread: 60, origin: { y: 0.7 } });
        }

        async function askQuestion() {
            const url = document.getElementById('urlInput').value;
            const q = document.getElementById('askInput').value;
            if(!url || !q) return Toast("Please enter both video URL and your question", "warning");

            const btn = document.getElementById('askBtn');
            const respBox = document.getElementById('qaResponse');
            
            btn.disabled = true;
            btn.innerHTML = '<div class="loader" style="width:12px;height:12px;"></div>';
            respBox.classList.remove('hidden');
            respBox.innerHTML = '<div class="flex items-center gap-2"><div class="loader"></div> Searching video transcript for answer...</div>';

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url, title: currentTitle, question: q, api_key: "" })
                });
                const data = await res.json();
                if(res.ok) {
                    respBox.innerHTML = `<strong>Answer:</strong>\n${data.answer}`;
                } else {
                    respBox.innerHTML = `<span class="text-red-400">${data.detail || 'Failed to get response'}</span>`;
                }
            } catch(e) {
                respBox.innerHTML = '<span class="text-red-400">Connection error.</span>';
            }
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="send" class="w-3.5 h-3.5"></i> Ask';
            lucide.createIcons();
        }

        function filterEditorView(mode) {
            currentEditorFilter = mode;
            document.getElementById('btnFilterAll').className = mode === 'all' ? 'text-purple-400 font-bold hover:underline' : 'text-slate-400 font-semibold hover:underline';
            document.getElementById('btnFilterStarred').className = mode === 'starred' ? 'text-yellow-400 font-bold hover:underline' : 'text-slate-400 font-semibold hover:underline';
            renderEditor();
        }

        function toggleStarSlide(file) {
            starredSlidesMap[file] = !starredSlidesMap[file];
            renderEditor();
            Toast(starredSlidesMap[file] ? "Added to Starred" : "Removed from Starred", "info");
        }

        function renderEditor() {
            const grid = document.getElementById('editorGrid');
            grid.innerHTML = '';
            
            let filesToRender = slidesArray;
            if(currentEditorFilter === 'starred') {
                filesToRender = slidesArray.filter(f => starredSlidesMap[f]);
            }

            document.getElementById('slideCount').innerText = `${filesToRender.length} slides`;
            
            if(filesToRender.length === 0) {
                grid.innerHTML = '<div class="col-span-full text-center py-10 text-slate-500">No slides found for this filter.</div>';
                return;
            }
            
            filesToRender.forEach((file, idx) => {
                const div = document.createElement('div');
                div.className = 'slide-card bg-gray-850 overflow-hidden border border-gray-700 shadow-md group flex flex-col justify-between';
                div.draggable = true;
                div.dataset.file = file;
                const isStarred = starredSlidesMap[file];
                
                div.innerHTML = `
                    <div onclick="openLightbox(${slidesArray.indexOf(file)})" class="relative w-full pb-[56.25%] bg-black cursor-zoom-in">
                        <img src="/api/image?task_id=${currentTaskId}&file=${file}" class="absolute top-0 left-0 w-full h-full object-cover preview-img transition-transform duration-300 group-hover:scale-105" draggable="false">
                    </div>
                    <div class="p-2 space-y-1.5 border-t border-gray-700 bg-gray-900/60">
                        <div class="flex justify-between items-center text-[10px] text-slate-400 font-mono">
                            <span class="truncate">#${slidesArray.indexOf(file) + 1} - ${file.replace('.jpg','')}</span>
                            <select onchange="slideTagsMap['${file}'] = this.value" class="bg-gray-950 text-slate-300 rounded border border-gray-800 text-[9px] outline-none px-1">
                                <option value="" ${!slideTagsMap[file] ? 'selected' : ''}>Tag...</option>
                                <option value="🔴 Exam Alert" ${slideTagsMap[file] === '🔴 Exam Alert' ? 'selected' : ''}>🔴 Exam</option>
                                <option value="🟢 Definition" ${slideTagsMap[file] === '🟢 Definition' ? 'selected' : ''}>🟢 Def</option>
                                <option value="🔵 Code" ${slideTagsMap[file] === '🔵 Code' ? 'selected' : ''}>🔵 Code</option>
                                <option value="🟡 Concept" ${slideTagsMap[file] === '🟡 Concept' ? 'selected' : ''}>🟡 Concept</option>
                            </select>
                        </div>
                        <input type="text" placeholder="Add custom note..." value="${slideNotesMap[file] || ''}" oninput="slideNotesMap['${file}'] = this.value" style="user-select: text;"
                               class="w-full bg-gray-950 border border-gray-700/60 rounded px-1.5 py-1 text-[10px] text-slate-200 outline-none focus:border-purple-500">
                    </div>
                    <div class="star-btn ${isStarred ? 'starred' : ''}" onclick="toggleStarSlide('${file}')"><i data-lucide="star" class="w-3.5 h-3.5"></i></div>
                    <div class="delete-btn" onclick="deleteSlide('${file}')"><i data-lucide="x" class="w-4 h-4"></i></div>
                `;
                
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

        function openLightbox(idx) {
            currentLightboxIndex = idx;
            const file = slidesArray[idx];
            document.getElementById('lightboxImg').src = `/api/image?task_id=${currentTaskId}&file=${file}`;
            document.getElementById('lightboxTitle').innerText = `Slide #${idx+1} - ${file}`;
            document.getElementById('lightboxModal').classList.remove('hidden');
        }

        function closeLightbox() {
            document.getElementById('lightboxModal').classList.add('hidden');
        }

        function nextLightbox() {
            if(slidesArray.length === 0) return;
            currentLightboxIndex = (currentLightboxIndex + 1) % slidesArray.length;
            openLightbox(currentLightboxIndex);
        }

        function prevLightbox() {
            if(slidesArray.length === 0) return;
            currentLightboxIndex = (currentLightboxIndex - 1 + slidesArray.length) % slidesArray.length;
            openLightbox(currentLightboxIndex);
        }

        /* FLASHCARD FUNCTIONS WITH SELF-TESTING SCORE */
        function openFlashcards() {
            if(slidesArray.length === 0) return Toast("No slides available for flashcards", "warning");
            currentFlashcardIndex = 0;
            flashcardRightCount = 0;
            flashcardTotalAttempted = 0;
            isFlashcardFlipped = false;
            renderFlashcard();
            document.getElementById('flashcardModal').classList.remove('hidden');
        }

        function closeFlashcards() {
            document.getElementById('flashcardModal').classList.add('hidden');
        }

        function flipFlashcard() {
            isFlashcardFlipped = !isFlashcardFlipped;
            const inner = document.getElementById('flashcardInner');
            if(isFlashcardFlipped) inner.classList.add('rotate-y-180');
            else inner.classList.remove('rotate-y-180');
        }

        function renderFlashcard() {
            isFlashcardFlipped = false;
            document.getElementById('flashcardInner').classList.remove('rotate-y-180');
            
            const file = slidesArray[currentFlashcardIndex];
            document.getElementById('flashcardCounter').innerText = `Card ${currentFlashcardIndex + 1} of ${slidesArray.length}`;
            const pct = flashcardTotalAttempted ? Math.round((flashcardRightCount / flashcardTotalAttempted) * 100) : 0;
            document.getElementById('flashcardScore').innerText = `Score: ${flashcardRightCount}/${flashcardTotalAttempted} (${pct}%)`;
            document.getElementById('flashcardImg').src = `/api/image?task_id=${currentTaskId}&file=${file}`;
            
            const note = slideNotesMap[file] || "No custom note added for this slide. Click to edit in editor.";
            document.getElementById('flashcardNote').innerText = note;
        }

        function scoreFlashcard(isCorrect) {
            flashcardTotalAttempted++;
            if(isCorrect) {
                flashcardRightCount++;
                confetti({ particleCount: 30, spread: 50, origin: { y: 0.8 } });
            }
            nextFlashcard();
        }

        function nextFlashcard() {
            if(slidesArray.length === 0) return;
            currentFlashcardIndex = (currentFlashcardIndex + 1) % slidesArray.length;
            renderFlashcard();
        }

        function prevFlashcard() {
            if(slidesArray.length === 0) return;
            currentFlashcardIndex = (currentFlashcardIndex - 1 + slidesArray.length) % slidesArray.length;
            renderFlashcard();
        }

        document.addEventListener('keydown', (e) => {
            if(e.key === '?') openHotkeyModal();

            if(!document.getElementById('lightboxModal').classList.contains('hidden')) {
                if(e.key === 'Escape') closeLightbox();
                if(e.key === 'ArrowRight') nextLightbox();
                if(e.key === 'ArrowLeft') prevLightbox();
            }
            if(!document.getElementById('flashcardModal').classList.contains('hidden')) {
                if(e.key === 'Escape') closeFlashcards();
                if(e.key === 'ArrowRight') nextFlashcard();
                if(e.key === 'ArrowLeft') prevFlashcard();
                if(e.key === ' ') { e.preventDefault(); flipFlashcard(); }
            }
        });

        function getDragAfterElement(container, y, x) {
            const draggableElements = [...container.querySelectorAll('.slide-card:not(.dragging)')];
            return draggableElements.reduce((closest, child) => {
                const box = child.getBoundingClientRect();
                const offsetX = x - box.left - box.width / 2;
                const offsetY = y - box.top - box.height / 2;
                const offset = Math.abs(offsetX) + Math.abs(offsetY); 
                if (offset < closest.offset && offsetY < box.height/2 && offsetX < box.width/2) {
                    return { offset: offset, element: child }
                } else return closest;
            }, { offset: Number.POSITIVE_INFINITY }).element;
        }

        function updateArrayFromDOM() {
            const cards = document.querySelectorAll('.slide-card');
            slidesArray = Array.from(cards).map(card => card.dataset.file);
            renderEditor();
        }

        function deleteSlide(file) {
            slidesArray = slidesArray.filter(f => f !== file);
            delete slideNotesMap[file];
            delete slideTagsMap[file];
            delete starredSlidesMap[file];
            renderEditor();
        }
        
        function clearAllSlides() {
            Swal.fire({
                title: 'Are you sure?', text: "You won't be able to revert this!", icon: 'warning',
                showCancelButton: true, confirmButtonColor: '#ef4444', cancelButtonColor: '#374151',
                confirmButtonText: 'Yes, delete all!', background: '#172033', color: '#fff'
            }).then((result) => {
                if (result.isConfirmed) { 
                    slidesArray = []; slideNotesMap = {}; slideTagsMap = {}; starredSlidesMap = {}; 
                    renderEditor(); 
                }
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
            if(slidesArray.length === 0 && format !== 'md') return Toast("No slides to export!", "warning");
            
            const invert = document.getElementById('invertToggle').checked;
            const enhance = document.getElementById('enhanceToggle').checked;
            const layout = parseInt(document.getElementById('exportLayout').value);
            const qualityVal = document.getElementById('exportQuality')?.value || 'high';
            
            const btn = event.currentTarget;
            const originalHTML = btn.innerHTML;
            btn.innerHTML = '<div class="loader" style="width:14px;height:14px;border-width:2px;"></div>';
            btn.disabled = true;
            
            try {
                const res = await fetch('/api/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        task_id: currentTaskId, selected_files: slidesArray, format: format, 
                        title: currentTitle, invert_colors: invert, enhance_text: enhance, 
                        layout: layout, quality: qualityVal, slide_notes: slideNotesMap, slide_tags: slideTagsMap 
                    })
                });
                
                if(res.ok) {
                    const blob = await res.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    const cleanTitle = currentTitle.replace(/[\\\\/*?:"<>|]/g, "_") || "Presentation";
                    a.download = `${cleanTitle}_Notes.${format}`;
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
            list.innerHTML = '<div class="text-center py-4"><div class="loader"></div></div>';
            
            try {
                const res = await fetch('/api/history');
                const data = await res.json();
                
                list.innerHTML = data.length ? '' : '<div class="text-center py-10 opacity-50"><i data-lucide="ghost" class="w-12 h-12 mx-auto mb-2 text-slate-500"></i><p>No history yet.</p></div>';
                
                data.forEach(item => {
                    list.innerHTML += `
                        <div class="bg-gray-850 p-4 rounded-xl border border-gray-700/50 flex justify-between items-center hover:bg-gray-800 transition-colors">
                            <div class="flex items-center gap-4">
                                <div class="bg-purple-900/30 p-2 rounded-lg text-purple-400"><i data-lucide="file-video" class="w-6 h-6"></i></div>
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

@app.get("/api/transcript")
def get_transcript_api(url: str):
    transcript = get_video_transcript(url)
    return {"transcript": transcript}

@app.post("/api/summary")
def get_summary_api(req: SummaryRequest):
    transcript = get_video_transcript(req.url)
    api_key = req.api_key or os.getenv("GEMINI_API_KEY")
    summary_data = generate_smart_summary(transcript, req.title, api_key)
    return summary_data

@app.post("/api/chat")
def chat_api(req: ChatRequest):
    transcript = get_video_transcript(req.url)
    api_key = req.api_key or os.getenv("GEMINI_API_KEY")
    response = answer_video_question(transcript, req.title, req.question, api_key)
    return response

@app.get("/api/download_media")
def download_media(url: str, type: str = "video", quality: str = "720p", bg_tasks: BackgroundTasks = None):
    try:
        task_id = str(uuid.uuid4())[0:8]
        safe_title = "media"
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl_info:
                info_dict = ydl_info.extract_info(url, download=False)
                safe_title = re.sub(r'[\\/*?:"<>|]', "_", info_dict.get('title', 'media'))
        except Exception:
            pass

        if type == "audio":
            out_template = os.path.join(TEMP_DIR, f"{task_id}_audio.%(ext)s")
            
            # Determine audio bitrate quality
            bitrate = "192"
            q_clean = str(quality).lower().replace("kbps", "").replace("k", "").strip()
            if q_clean in ["320", "best", "high"]: bitrate = "320"
            elif q_clean in ["256"]: bitrate = "256"
            elif q_clean in ["192", "medium", "standard"]: bitrate = "192"
            elif q_clean in ["128", "low", "light"]: bitrate = "128"
            elif q_clean.isdigit(): bitrate = q_clean

            dl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': out_template,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': bitrate,
                }],
                'quiet': True,
            }
            media_type = "audio/mpeg"

            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                ydl.download([url])

            out_file = os.path.join(TEMP_DIR, f"{task_id}_audio.mp3")
            filename = f"{safe_title}_{bitrate}kbps.mp3"

        elif type == "video":
            out_template = os.path.join(TEMP_DIR, f"{task_id}_video.%(ext)s")
            
            q_clean = str(quality).lower().strip()
            height_limit = "720"
            quality_label = "720p"
            
            if q_clean in ["2160p", "2160", "4k"]:
                height_limit = "2160"
                quality_label = "4K_2160p"
            elif q_clean in ["1440p", "1440", "2k"]:
                height_limit = "1440"
                quality_label = "2K_1440p"
            elif q_clean in ["1080p", "1080", "fhd"]:
                height_limit = "1080"
                quality_label = "1080p"
            elif q_clean in ["720p", "720", "hd"]:
                height_limit = "720"
                quality_label = "720p"
            elif q_clean in ["480p", "480", "sd"]:
                height_limit = "480"
                quality_label = "480p"
            elif q_clean in ["360p", "360"]:
                height_limit = "360"
                quality_label = "360p"
            
            dl_opts = {
                'format': f'bestvideo[height<={height_limit}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height_limit}]+bestaudio/best[height<={height_limit}][ext=mp4]/best[height<={height_limit}]/best',
                'outtmpl': out_template,
                'quiet': True,
            }
            media_type = "video/mp4"

            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                ydl.download([url])

            out_file = None
            for f in os.listdir(TEMP_DIR):
                if f.startswith(f"{task_id}_video."):
                    out_file = os.path.join(TEMP_DIR, f)
                    break
            filename = f"{safe_title}_{quality_label}.mp4"

        elif type == "subtitles":
            transcript = get_video_transcript(url)
            if not transcript:
                raise HTTPException(status_code=404, detail="No subtitles available for this video.")
            out_file = os.path.join(TEMP_DIR, f"{task_id}_subtitles.srt")
            with open(out_file, "w", encoding="utf-8") as f:
                for idx, item in enumerate(transcript, 1):
                    sec_start = int(item['start'])
                    sec_end = int(item['start'] + item.get('duration', 3))
                    m1, s1 = divmod(sec_start, 60); h1, m1 = divmod(m1, 60)
                    m2, s2 = divmod(sec_end, 60); h2, m2 = divmod(m2, 60)
                    f.write(f"{idx}\n{h1:02d}:{m1:02d}:{s1:02d},000 --> {h2:02d}:{m2:02d}:{s2:02d},000\n{item['text']}\n\n")
            filename = f"{safe_title}_Subtitles.srt"
            media_type = "text/plain"
        else:
            raise HTTPException(status_code=400, detail="Invalid media download type")

        if not out_file or not os.path.exists(out_file):
            raise HTTPException(status_code=500, detail="Media file download failed.")

        if bg_tasks:
            bg_tasks.add_task(cleanup_file, out_file)

        return FileResponse(path=out_file, filename=filename, media_type=media_type)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/extract")
def extract_slides(url: str, rate: str = "smart", sens: str = "0.15", start: str = None, end: str = None):
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=500, detail="FFmpeg is not installed on the system.")

    task_id = str(uuid.uuid4())[0:8]
    video_template = os.path.join(TEMP_DIR, f"{task_id}_vid.%(ext)s")
    
    dl_opts = {'format': 'bestvideo[height<=480]', 'outtmpl': video_template, 'noplaylist': True}
    
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
            vf_filter = "fps=1"
            vsync = []
        else:
            vf_filter = f"fps=1/{rate}"
            vsync = []
            
        cmd = ["ffmpeg", "-y", "-i", video_file, "-filter:v", vf_filter] + vsync + [os.path.join(out_folder, "slide_%03d.jpg")]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        cleanup_file(video_file)
        files = sorted([f for f in os.listdir(out_folder) if f.endswith('.jpg')])
        
        if rate == "smart" and len(files) > 1:
            filtered_files = [files[0]]
            last_kept_path = os.path.join(out_folder, files[0])
            
            try:
                last_img = Image.open(last_kept_path).convert('L').resize((128, 128))
            except:
                last_img = None
            
            threshold = float(sens) * 80  
            
            for f in files[1:]:
                curr_path = os.path.join(out_folder, f)
                if not last_img:
                    filtered_files.append(f)
                    last_kept_path = curr_path
                    try: last_img = Image.open(curr_path).convert('L').resize((128, 128))
                    except: pass
                    continue

                try:
                    curr_img = Image.open(curr_path).convert('L').resize((128, 128))
                    diff = ImageChops.difference(last_img, curr_img)
                    stat = ImageStat.Stat(diff)
                    mae = stat.mean[0]
                    
                    if mae > threshold:  
                        filtered_files.append(f)
                        last_img = curr_img
                    else:
                        os.remove(curr_path)
                except Exception as e:
                    filtered_files.append(f) 
                    try: last_img = Image.open(curr_path).convert('L').resize((128, 128))
                    except: pass
            
            files = filtered_files
        
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
    if not os.path.exists(task_folder) and data.format not in ["md", "txt"]:
        raise HTTPException(status_code=404, detail="Session expired")

    safe_title = re.sub(r'[\\/*?:"<>|]', "_", data.title)
    out_file = os.path.join(TEMP_DIR, f"{safe_title}_{data.task_id}.{data.format}")

    images = []
    if os.path.exists(task_folder):
        for f in data.selected_files:
            p = os.path.join(task_folder, f)
            if os.path.exists(p):
                img = Image.open(p).convert('RGB')
                if data.invert_colors: 
                    img = ImageOps.invert(img)
                if data.enhance_text:
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(1.5)
                    sharpener = ImageEnhance.Sharpness(img)
                    img = sharpener.enhance(2.0)
                images.append(img)
            
    if data.format == "pdf":
        if not images: raise HTTPException(status_code=400, detail="No valid images for PDF")
        
        cover = create_pdf_cover_page(images[0].width, images[0].height, data.title, data.author_name, data.subject_tag, len(data.selected_files))
        pdf_images = [cover] + images
        
        if data.layout > 1:
            processed = [cover]
            for i in range(0, len(images), data.layout):
                batch = images[i:i+data.layout]
                bg_w, bg_h = images[0].size
                if data.layout == 2:
                    canvas = Image.new('RGB', (bg_w, bg_h * 2), (255,255,255))
                    canvas.paste(batch[0], (0, 0))
                    if len(batch)>1: canvas.paste(batch[1], (0, bg_h))
                else:
                    canvas = Image.new('RGB', (bg_w * 2, bg_h * 2), (255,255,255))
                    canvas.paste(batch[0], (0, 0))
                    if len(batch)>1: canvas.paste(batch[1], (bg_w, 0))
                    if len(batch)>2: canvas.paste(batch[2], (0, bg_h))
                    if len(batch)>3: canvas.paste(batch[3], (bg_w, bg_h))
                processed.append(canvas)
            pdf_images = processed
            
        pdf_images[0].save(out_file, save_all=True, append_images=pdf_images[1:])
        mt = 'application/pdf'

    elif data.format == "zip":
        if not images: raise HTTPException(status_code=400, detail="No valid images for ZIP")
        with zipfile.ZipFile(out_file, 'w') as zipf:
            for idx, img in enumerate(images):
                temp_img = os.path.join(TEMP_DIR, f"temp_{idx}.jpg")
                img.save(temp_img)
                zipf.write(temp_img, arcname=data.selected_files[idx])
                os.remove(temp_img)
        mt = 'application/zip'

    elif data.format == "txt":
        text_content = f"--- Extracted Notes: {data.title} ---\n\n"
        if HAS_OCR and images:
            for idx, img in enumerate(images):
                f_name = data.selected_files[idx]
                note = data.slide_notes.get(f_name, "").strip()
                tag = data.slide_tags.get(f_name, "").strip()
                text_content += f"--- Slide {idx+1} ({f_name}) ---\n"
                if tag: text_content += f"Tag: {tag}\n"
                if note: text_content += f"Note: {note}\n\n"
                try:
                    text = pytesseract.image_to_string(img)
                    text_content += text.strip() + "\n\n"
                except Exception as e:
                    text_content += f"[OCR Error: {str(e)}]\n\n"
        else:
            text_content += f"Slide Count: {len(data.selected_files)}\n"
        
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(text_content)
        mt = "text/plain"

    elif data.format == "md":
        md_content = f"# 📚 Study Notes: {data.title}\n\n"
        md_content += f"**Total Extracted Slides:** {len(data.selected_files)}\n\n"
        md_content += "## 📌 Slide Overview & Custom Notes\n\n"
        for idx, f in enumerate(data.selected_files):
            md_content += f"### Slide #{idx+1} (`{f}`)\n"
            tag = data.slide_tags.get(f, "").strip()
            note = data.slide_notes.get(f, "").strip()
            if tag: md_content += f"🏷️ **Tag**: `{tag}`\n\n"
            if note: md_content += f"> ✍️ **Custom Note**: {note}\n\n"
            if HAS_OCR and idx < len(images):
                try:
                    ocr_txt = pytesseract.image_to_string(images[idx]).strip()
                    if ocr_txt:
                        md_content += f"```text\n{ocr_txt}\n```\n\n"
                except Exception:
                    pass
        
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        mt = "text/markdown"

    elif data.format == "pptx":
        if not HAS_PPTX: raise HTTPException(status_code=400, detail="python-pptx not installed")
        if not images: raise HTTPException(status_code=400, detail="No valid images for PPTX")
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5) 
        
        # Add Title Slide
        title_slide = prs.slides.add_slide(prs.slide_layouts[0])
        title_slide.shapes.title.text = data.title
        title_slide.placeholders[1].text = f"Extracted Slides Notes • {time.strftime('%Y-%m-%d')}"

        for img in images:
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            temp_img = os.path.join(TEMP_DIR, f"pptx_temp_{uuid.uuid4().hex[:6]}.jpg")
            img.save(temp_img)
            slide.shapes.add_picture(temp_img, 0, 0, width=prs.slide_width, height=prs.slide_height)
            os.remove(temp_img)
        prs.save(out_file)
        mt = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")
    
    bg_tasks.add_task(cleanup_file, out_file)
    return FileResponse(path=out_file, filename=os.path.basename(out_file), media_type=mt)

def run_server():
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host=host, port=port, log_level="error")

if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2)
    try:
        window = webview.create_window('YT Extractor Pro Ultimate', 'http://127.0.0.1:8000', width=1250, height=880)
        webview.start()
    except:
        print("UI module failed. Open http://127.0.0.1:8000 in Chrome/Edge.")
        t.join()