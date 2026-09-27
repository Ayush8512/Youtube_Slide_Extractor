import os
import sys
import shutil
import zipfile
import urllib.request
import tempfile

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
HTML_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "index.html")

TEMP_DIR = tempfile.gettempdir()
HISTORY_FILE = os.path.join(TEMP_DIR, "yt_extractor_history.json")
BIN_DIR = os.path.join(BASE_DIR, "bin")

TRANSCRIPT_CACHE = {}

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


def load_env_file():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception as e:
            print(f"Warning: Could not read .env file: {e}")


def ensure_ffmpeg():
    """Ensures FFmpeg is available on the system; downloads win-64 binary into bin/ if missing."""
    if shutil.which("ffmpeg"):
        return True

    os.makedirs(BIN_DIR, exist_ok=True)
    bin_ffmpeg = os.path.join(BIN_DIR, "ffmpeg.exe")
    if os.path.exists(bin_ffmpeg):
        os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")
        return True

    print("⏳ FFmpeg missing! Checking or downloading automatically...")
    try:
        ffmpeg_url = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-win-64.zip"
        zip_path = os.path.join(BIN_DIR, "ffmpeg.zip")
        urllib.request.urlretrieve(ffmpeg_url, zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(BIN_DIR)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")
        print("✅ FFmpeg successfully installed!")
        return True
    except Exception as e:
        print(f"❌ FFmpeg auto-download failed: {e}")
        return False


def setup_env():
    load_env_file()
    os.makedirs(BIN_DIR, exist_ok=True)
    os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")
