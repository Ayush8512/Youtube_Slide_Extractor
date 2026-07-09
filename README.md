🚀 YT Extractor Pro Ultimate

Welcome to YT Extractor Pro Ultimate – an advanced, all-in-one tool designed to extract presentation slides, lecture notes, and screenshots from any YouTube video automatically!

Whether you are a student taking notes from a 2-hour lecture or a professional saving webinar slides, this tool uses smart AI-based scene detection to grab only the necessary frames and compile them into beautifully formatted PDFs, PowerPoint presentations, or ZIP files.

✨ Supercharged Features

🤖 Smart Scene Detection: Doesn't just take blind screenshots. The AI detects when a slide actually changes and captures it.

✂️ Video Trimming: Select custom Start and End times to only extract slides from a specific portion of the video.

🖱️ Pro Editor (Drag & Drop): Review all captured slides in a Grid View. Reorder them using Drag & Drop, or delete the junk ones before exporting!

🌙 Dark Mode / Invert Colors: One-click toggle to invert bright white slides into dark mode for eye-friendly reading.

📄 Multi-Format Export: * PDF: With customizable layouts (1, 2, or 4 slides per page).

PPTX: Native PowerPoint presentation export.

ZIP: Download all raw High-Quality images.

TXT (OCR): Extract raw text directly from the slides using Tesseract OCR.

🖥️ Desktop App Experience: Runs completely standalone with a modern dark-themed UI (No ugly terminals needed!).

⚙️ Auto FFmpeg Setup: No need to manually mess with system variables. The app downloads and configures FFmpeg automatically!

🛠️ Requirements & Installation

To run this software, you need Python 3.8+ installed on your system.

Step 1: Install Python Dependencies

Open your terminal or command prompt in the project folder and run the following command to install all required libraries:

pip install fastapi uvicorn yt-dlp Pillow python-pptx pywebview pytesseract



Step 2: (Optional but Recommended) Install Tesseract for OCR

If you want to use the "Extract Text (OCR)" feature to convert slide images into text notes, you must install the Tesseract software on your computer.

Windows: Download the installer from UB-Mannheim Tesseract GitHub and install it.

Mac: brew install tesseract

Linux: sudo apt install tesseract-ocr

(If you don't install this, the app will still work perfectly, but the OCR button will throw a missing dependency error).

🚀 How to Run

It's super simple. Just run the main Python file:

python app.py



A beautiful Desktop Window will pop up automatically.

Paste any YouTube Link and click "Fetch Data".

Adjust your settings (Smart mode, Start/End time, Sensitivity).

Click "Start Smart Extraction".

Once extracted, the Pro Editor will open. Delete bad slides, drag to reorder, and click Save PDF or PPTX!

🌐 Deployment (Vercel)

Want to host this on the web so you don't have to run it locally? This project is fully compatible with Vercel using serverless functions!

Ensure app.py, vercel.json, and requirements.txt are in the root folder.

Push to GitHub and import to Vercel.

Note: Vercel has a 10-second timeout limit on the free tier, so extremely long videos might time out during extraction. For heavy usage, consider deploying on Render or Railway.

🤝 Troubleshooting

FFmpeg not found? Don't worry! The script is designed to automatically download a lightweight version of FFmpeg into a bin folder when you run it the first time. Make sure you have an active internet connection.

Missing python-pptx error? Run pip install python-pptx.

Screen goes blank? Sometimes the WebView engine acts up. If the desktop window doesn't load, simply open your Chrome/Edge browser and go to http://127.0.0.1:8000.

Author- Ayush Pandey
