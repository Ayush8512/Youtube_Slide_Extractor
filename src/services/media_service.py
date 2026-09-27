import os
import re
import uuid
import json
import urllib.request
import yt_dlp
from fastapi import HTTPException
from src.config import TEMP_DIR, TRANSCRIPT_CACHE
from src.services.history_service import cleanup_file

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



def get_video_info(url: str):
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {"title": info.get('title', 'Unknown'), "uploader": info.get('uploader', 'Unknown')}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def process_media_download(url: str, type: str = "video", quality: str = "720p", bg_tasks=None):
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

        return out_file, filename, media_type

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
