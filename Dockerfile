# Production Dockerfile for YouTube Slide Extractor & Downloader
FROM python:3.10-slim

# Install system dependencies (FFmpeg & Tesseract OCR for Linux Cloud Servers)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirement list and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose port (7860 for Hugging Face Spaces / 10000 for Render)
EXPOSE 7860

# Run FastAPI app with Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
