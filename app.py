import os
import uuid
from flask import Flask, render_template, request, jsonify, session, send_file
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai # Menggunakan library terbaru agar tidak ada warning
from fpdf import FPDF

app = Flask(__name__)

# --- FIX SESSION (Agar Tidak Mental ke Login) ---
app.secret_key = "WIRADATA_78_STABLE_KEY" 
app.config.update(
    SESSION_COOKIE_SAMESITE='None', # Penting buat Hugging Face
    SESSION_COOKIE_SECURE=True
)

# 1. KONFIGURASI AI (NAMA KEY: geminiapikey)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

# 2. DATABASE USER
users_db = {
    "admin": {"password": "123", "role": "premium", "credits": 999},
    "guest": {"password": "guest", "role": "free", "credits": 3}
}

# --- FUNGSI PENDUKUNG ---

def create_pdf(text, filename):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)
    clean_text = text.encode('latin-1', 'ignore').decode('latin-1')
    pdf.multi_cell(0, 10, txt=clean_text)
    if not os.path.exists("downloads"): os.makedirs("downloads")
    path = os.path.join("downloads", filename)
    pdf.output(path)
    return path

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    u, p = data.get('username'), data.get('password')
    if u in users_db and users_db[u]['password'] == p:
        session['user'] = u
        session.permanent = True 
        return jsonify({"status": "success", "user": {"username": u, "credits": users_db[u]['credits']}})
    return jsonify({"status": "error", "message": "Login Gagal!"}), 401

@app.route('/api/analyze', methods=['POST'])
def analyze():
    if 'user' not in session:
        return jsonify({"error": "Sesi berakhir, silakan login kembali."}), 403
    
    user_id = session['user']
    if users_db[user_id]['credits'] <= 0:
        return jsonify({"error": "Kredit habis!"}), 403

    data = request.json
    url, mode = data.get('url'), data.get('mode')

    try:
        # Ekstraksi Transkrip (Cara paling aman)
        video_id = url.split("v=")[1].split("&")[0] if "v=" in url else url.split("/")[-1]
        
        # Panggil class method secara eksplisit
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['id', 'en'])
        raw_text = " ".join([t['text'] for t in transcript_list])

        # Proses AI dengan SDK Baru
        prompts = {
            "edukasi": f"Buat modul ajar SD Pasuruan dari: {raw_text}",
            "kreator": f"Ide konten TikTok PROJECT.78 dari: {raw_text}",
            "bisnis": f"Copywriting Warung Pro dari: {raw_text}"
        }
        
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompts.get(mode, "Ringkas: " + raw_text)
        )
        
        users_db[user_id]['credits'] -= 1
        session['last_result'] = response.text
        return jsonify({"result": response.text, "remaining_credits": users_db[user_id]['credits']})
    except Exception as e:
        return jsonify({"error": f"Gagal memproses: {str(e)}"}), 500

@app.route('/api/export-pdf')
def export_pdf():
    content = session.get('last_result')
    file_path = create_pdf(content, f"Hasil_Pipeline_{uuid.uuid4().hex[:6]}.pdf")
    return send_file(file_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=False, port=7860, host='0.0.0.0')