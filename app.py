import os
import threading
import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src.config import setup_env, HTML_TEMPLATE_PATH
from src.routes.api import router as api_router

# Setup environment & download FFmpeg if missing
setup_env()

app = FastAPI(title="YT Extractor Pro Ultimate")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Router
app.include_router(api_router)

# Serve Frontend UI
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    if os.path.exists(HTML_TEMPLATE_PATH):
        with open(HTML_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>YT Extractor UI template not found</h1>"

try:
    import gradio as gr
    demo = gr.mount_gradio_app(app, gr.Blocks(), path="/")
except Exception:
    demo = None

def run_server():
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host=host, port=port, log_level="error")

if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2)
    try:
        import webview
        window = webview.create_window('YT Extractor Pro Ultimate', 'http://127.0.0.1:8000', width=1250, height=880)
        webview.start()
    except Exception:
        print("UI module failed. Open http://127.0.0.1:8000 in Chrome/Edge.")
        t.join()
