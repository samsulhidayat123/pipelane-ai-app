import os
import uuid
from flask import Flask, render_template, request, jsonify, session, send_file
from youtube_transcript_api import YouTubeTranscriptApi
import google.generativeai as genai
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "DECON_78_SECRET" # Ganti sesukamu

# 1. KONFIGURASI AI
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 2. DATABASE SEDERHANA (In-Memory)
# Untuk SaaS asli, hubungkan ke Firebase yang pernah kamu pelajari
users_db = {
    "admin": {"password": "123", "role": "premium", "credits": 999},
    "guest": {"password": "guest", "role": "free", "credits": 3}
}

# --- FUNGSI TOOLS ---
def create_pdf(text, filename):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    # Membersihkan karakter non-latin agar tidak error
    clean_text = text.encode('latin-1', 'ignore').decode('latin-1')
    pdf.multi_cell(0, 10, txt=clean_text)
    path = os.path.join("downloads", filename)
    pdf.output(path)
    return path

# --- ROUTES AUTH ---
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    u, p = data.get('username'), data.get('password')
    if u in users_db and users_db[u]['password'] == p:
        session['user'] = u
        return jsonify({"status": "success", "user": users_db[u]})
    return jsonify({"status": "error", "message": "Login Gagal"}), 401

# --- ROUTES CORE ---
@app.route('/api/analyze', methods=['POST'])
def analyze():
    if 'user' not in session:
        return jsonify({"error": "Silakan login dulu bro!"}), 403
    
    user_id = session['user']
    if users_db[user_id]['credits'] <= 0:
        return jsonify({"error": "Kredit habis! Hubungi Warung Pro."}), 403

    data = request.json
    url, mode = data.get('url'), data.get('mode')

    try:
        # Ekstraksi Transkrip
        video_id = url.split("v=")[1].split("&")[0] if "v=" in url else url.split("/")[-1]
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['id', 'en'])
        raw_text = " ".join([t['text'] for t in transcript])

        # Proses AI
        prompts = {
            "edukasi": f"Buat modul ajar SD Pasuruan dari teks ini: {raw_text}",
            "kreator": f"Cari hook TikTok Project.78 dari: {raw_text}",
            "bisnis": f"Buat copy jualan Warung Pro dari: {raw_text}"
        }
        response = model.generate_content(prompts.get(mode))
        
        # Kurangi Kredit
        users_db[user_id]['credits'] -= 1
        
        # Simpan hasil sementara untuk PDF
        session['last_result'] = response.text
        return jsonify({"result": response.text, "remaining_credits": users_db[user_id]['credits']})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/export-pdf')
def export_pdf():
    content = session.get('last_result', 'No content')
    if not os.path.exists("downloads"): os.makedirs("downloads")
    file_path = create_pdf(content, f"Modul_WiraData_{uuid.uuid4().hex[:6]}.pdf")
    return send_file(file_path, as_attachment=True)

@app.route('/')
def index(): return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=False, port=7860, host='0.0.0.0')