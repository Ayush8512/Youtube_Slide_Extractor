from pydantic import BaseModel
from typing import Optional, List, Dict

class GenerateData(BaseModel):
    task_id: str
    selected_files: List[str]
    format: str
    title: str
    invert_colors: bool = False
    enhance_text: bool = False
    layout: int = 1
    quality: str = "high"
    slide_notes: Dict[str, str] = {}
    slide_tags: Dict[str, str] = {}
    starred_files: List[str] = []
    author_name: str = ""
    subject_tag: str = ""

class SummaryRequest(BaseModel):
    url: str
    title: str = ""
    api_key: Optional[str] = None

class ChatRequest(BaseModel):
    url: str
    title: str = ""
    question: str
    api_key: Optional[str] = None
