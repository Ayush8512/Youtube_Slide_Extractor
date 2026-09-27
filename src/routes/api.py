import os
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from src.config import TEMP_DIR
from src.models import GenerateData, SummaryRequest, ChatRequest
from src.services.history_service import load_history, cleanup_file
from src.services.media_service import get_video_info, get_video_transcript, process_media_download
from src.services.ai_service import generate_smart_summary, answer_video_question
from src.services.slide_service import extract_slides_process, generate_file_process

router = APIRouter(prefix="/api", tags=["API"])

@router.get("/info")
def get_video_info_api(url: str):
    return get_video_info(url)

@router.get("/transcript")
def get_transcript_api(url: str):
    transcript = get_video_transcript(url)
    return {"transcript": transcript}

@router.post("/summary")
def get_summary_api(req: SummaryRequest):
    transcript = get_video_transcript(req.url)
    api_key = req.api_key or os.getenv("GEMINI_API_KEY")
    summary_data = generate_smart_summary(transcript, req.title, api_key)
    return summary_data

@router.post("/chat")
def chat_api(req: ChatRequest):
    transcript = get_video_transcript(req.url)
    api_key = req.api_key or os.getenv("GEMINI_API_KEY")
    response = answer_video_question(transcript, req.title, req.question, api_key)
    return response

@router.get("/download_media")
def download_media(url: str, type: str = "video", quality: str = "720p", bg_tasks: BackgroundTasks = None):
    out_file, filename, media_type = process_media_download(url, type, quality)
    if bg_tasks:
        bg_tasks.add_task(cleanup_file, out_file)
    return FileResponse(path=out_file, filename=filename, media_type=media_type)

@router.get("/extract")
def extract_slides(url: str, rate: str = "smart", sens: str = "0.15", start: str = None, end: str = None):
    return extract_slides_process(url, rate, sens, start, end)

@router.get("/image")
def get_image(task_id: str, file: str):
    path = os.path.join(TEMP_DIR, f"task_{task_id}", file)
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Image not found")

@router.get("/history")
def get_history_api():
    return load_history()

@router.post("/generate")
def generate_file(data: GenerateData, bg_tasks: BackgroundTasks):
    out_file, media_type = generate_file_process(data)
    bg_tasks.add_task(cleanup_file, out_file)
    return FileResponse(path=out_file, filename=os.path.basename(out_file), media_type=media_type)
