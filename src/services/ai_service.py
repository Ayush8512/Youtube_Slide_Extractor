import os
import re
import json
import urllib.request

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

