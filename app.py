import os
import uuid
from flask import Flask, render_template, request, jsonify, session, send_file
from youtube_transcript_api import YouTubeTranscriptApi
import google.generativeai as genai
from fpdf import FPDF

app = Flask(__name__)

# --- PERBAIKAN SESSION ---
# Gunakan string tetap agar login tidak mental/sesi berakhir saat server restart
app.secret_key = "WIRADATA_SAMSUL_78_STABLE_KEY" 

# 1. KONFIGURASI AI (GEMINI 1.5 FLASH)
# Nama key disesuaikan dengan yang kamu minta: GEMINI_API_KEY
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    # Warning jika key belum terpasang di Settings > Secrets
    print("WARNING: GEMINI_API_KEY tidak ditemukan di environment variables!")

# 2. DATABASE USER (MVP MODE)
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
    
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    
    path = os.path.join("downloads", filename)
    pdf.output(path)
    return path

def get_yt_transcript(url):
    try:
        video_id = url.split("v=")[1].split("&")[0] if "v=" in url else url.split("/")[-1]
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['id', 'en'])
        return " ".join([t['text'] for t in transcript])
    except Exception as e:
        return f"Error: Gagal ekstraksi transkrip ({str(e)})"

# --- ROUTES APLIKASI ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    u, p = data.get('username'), data.get('password')
    if u in users_db and users_db[u]['password'] == p:
        session.permanent = True # Memperkuat sesi login
        session['user'] = u
        return jsonify({"status": "success", "user": {"username": u, "credits": users_db[u]['credits']}})
    return jsonify({"status": "error", "message": "Username atau Password salah!"}), 401

@app.route('/api/analyze', methods=['POST'])
def analyze():
    if 'user' not in session:
        return jsonify({"error": "Sesi berakhir, silakan login kembali."}), 403
    
    user_id = session['user']
    if users_db[user_id]['credits'] <= 0:
        return jsonify({"error": "Kredit habis! Hubungi Warung Pro."}), 403

    data = request.json
    url, mode = data.get('url'), data.get('mode')

    raw_text = get_yt_transcript(url)
    if "Error" in raw_text:
        return jsonify({"error": raw_text}), 500

    prompts = {
        "edukasi": f"Ubah transkrip ini menjadi modul ajar SD yang ceria. Tambahkan 3 soal latihan: {raw_text}",
        "kreator": f"Analisis video untuk TikTok PROJECT.78. Cari 3 hook viral: {raw_text}",
        "bisnis": f"Buat copywriting jualan di Warung Pro dari video ini: {raw_text}"
    }
    
    try:
        response = model.generate_content(prompts.get(mode, "Ringkas teks ini: " + raw_text))
        final_result = response.text
        
        users_db[user_id]['credits'] -= 1
        session['last_result'] = final_result
        
        return jsonify({
            "result": final_result, 
            "remaining_credits": users_db[user_id]['credits']
        })
    except Exception as e:
        return jsonify({"error": f"AI Error: {str(e)}"}), 500

@app.route('/api/export-pdf')
def export_pdf():
    content = session.get('last_result')
    if not content:
        return "Tidak ada data untuk dicetak", 400
        
    file_path = create_pdf(content, f"Hasil_Pipeline_{uuid.uuid4().hex[:6]}.pdf")
    return send_file(file_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=False, port=7860, host='0.0.0.0')