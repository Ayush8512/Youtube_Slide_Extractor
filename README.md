# 🚀 YT Extractor Pro Ultimate

**YT Extractor Pro Ultimate** is an advanced desktop and web application built with Python (FastAPI + Tailwind CSS + PyWebView + Mermaid.js) designed to extract slides from YouTube videos, download videos in multiple resolutions (4K, 2K, 1080p, 720p, 480p, 360p) & MP3 audio (320k, 256k, 192k, 128k), generate AI video summaries & concept mindmaps, run interactive video quizzes, display searchable transcripts with timestamp video seeking, provide an AI Q&A video assistant, and export study notes in multiple formats.

---

## ✨ Key Features & Power-Ups

### 1. 🎬 Direct Video & Audio Quality Downloader (yt-dlp Engine)
- **1-Click Video Download**: Download YouTube videos directly from top bar or player controls.
- **Resolution Selector**: Choose between **4K (2160p)**, **2K (1440p)**, **1080p Full HD**, **720p HD**, **480p SD**, or **360p** MP4 formats.
- **Audio Bitrate Selector**: Download high-quality `.mp3` audio in **320 kbps**, **256 kbps**, **192 kbps**, or **128 kbps**.
- **Subtitles**: Download `.srt` subtitle files.

### 2. ⚡ Free Offline NLP Summary & Q&A Engine
- **Engine Selector**: Choose between **⚡ Free Offline NLP (No API Key Needed)** and **🤖 Gemini AI Engine**.
- **Clickable Timestamp Jump Links**: In Video Q&A, timestamp references (e.g. `⏱️ 01:45`) are interactive buttons that seek the video player to that exact moment.

### 3. 🔍 Slide Image Enhancer & Sharpen Text Filter
- **High Contrast & Sharpening**: 1-click text sharpener filter (`ImageEnhance.Contrast` + `ImageEnhance.Sharpness`) to make small/blurry slide text crisp and easy to read.

### 4. ⭐ Slide Favorites & Starred System
- **Bookmark Important Slides**: Click the ⭐ icon on any slide thumbnail to bookmark it.
- **Starred Filter**: Filter your editor view to show **"All Slides"** vs **"⭐ Starred Slides Only"** for quick exam review!

### 5. 🏷️ Color-Coded Tagging System
- Assign custom study tags to individual slides:
  - 🔴 `Exam Alert`
  - 🟢 `Definition`
  - 🔵 `Code Snippet`
  - 🟡 `Key Concept`
- Tags are automatically exported into your Markdown (`.MD`) and Text (`.TXT`) study notes!

### 6. 📖 Professional Cover Page Generator (PDF & PPTX)
- Auto-generates a clean, branded Cover Page for exported PDFs and PPTX presentations containing the Video Title, Presenter Name, Subject Tag, Date, and Total Slide Count.

### 7. 🃏 3D Study Flashcards with Self-Testing Score Deck
- Interactive 3D flip card memory revision mode with score tracking and confetti!

---

## 🛠️ Prerequisites & Installation

### 1. Requirements
- **Python 3.9+** installed on your system.
- **FFmpeg** (Auto-downloaded into `bin/` directory on first run if missing).
- *(Optional)* **Tesseract OCR** for text extraction from slide images.

### 2. Installation Steps

Clone or download this repository and navigate to the folder:

```bash
git clone https://github.com/Ayush8512/Youtube_Slide_Extractor.git
cd Youtube_Slide_Extractor
```

Install the required Python dependencies:

```bash
pip install -r requirements.txt
```

---

## 🐳 Docker & Cloud Deployment (Hugging Face / Render)

This application includes a production-ready `Dockerfile` and `render.yaml` for instant cloud deployment:

- **Hugging Face Spaces**: Create a Docker Space, connect repository, and run live!
- **Render.com**: Connect repository and select Docker runtime for 1-click hosting.

---

## 🚀 Running Locally

### Method 1: Using Batch Script (Windows)
Double-click `Yt_Slide_Extractor.bat` or run in terminal:

```cmd
Yt_Slide_Extractor.bat
```

### Method 2: Running via Python
Run `app.py` directly:

```bash
python app.py
```

Open your browser and navigate to: `http://127.0.0.1:8000`

---

## 🤝 Author & License
Author: **Ayush Pandey**
