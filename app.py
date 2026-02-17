import os
import uuid
import re
from flask import Flask, render_template, request, jsonify, session, send_file
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from fpdf import FPDF

# ===============================
# INIT APP
# ===============================
app = Flask(__name__)
app.secret_key = "WIRADATA_78_STABLE_KEY"

app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True
)

# ===============================
# GEMINI CONFIG
# ===============================
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

# ===============================
# SIMPLE USER DB
# ===============================
users_db = {
    "admin": {"password": "123", "role": "premium", "credits": 999},
    "guest": {"password": "guest", "role": "free", "credits": 3}
}

# ===============================
# HELPER FUNCTIONS
# ===============================

def extract_video_id(url):
    """
    Ekstrak video ID dari berbagai format URL YouTube
    """
    patterns = [
        r"v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"embed/([a-zA-Z0-9_-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def create_pdf(text, filename):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)

    clean_text = text.encode("latin-1", "ignore").decode("latin-1")
    pdf.multi_cell(0, 8, txt=clean_text)

    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    path = os.path.join("downloads", filename)
    pdf.output(path)
    return path


# ===============================
# ROUTES
# ===============================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if username in users_db and users_db[username]["password"] == password:
        session["user"] = username
        session.permanent = True

        return jsonify({
            "status": "success",
            "user": {
                "username": username,
                "credits": users_db[username]["credits"]
            }
        })

    return jsonify({"status": "error", "message": "Login Gagal!"}), 401


@app.route("/api/analyze", methods=["POST"])
def analyze():
    # Cek login
    if "user" not in session:
        return jsonify({"error": "Sesi berakhir, silakan login kembali."}), 403

    user_id = session["user"]

    # Cek kredit
    if users_db[user_id]["credits"] <= 0:
        return jsonify({"error": "Kredit habis!"}), 403

    # Cek API Key
    if not client:
        return jsonify({"error": "GEMINI_API_KEY belum dikonfigurasi."}), 500

    data = request.json
    url = data.get("url")
    mode = data.get("mode")

    if not url:
        return jsonify({"error": "URL tidak boleh kosong"}), 400

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({"error": "URL YouTube tidak valid"}), 400

    try:
        # ===============================
        # FETCH TRANSCRIPT (NEW METHOD)
        # ===============================
        ytt = YouTubeTranscriptApi()
        transcript_list = ytt.fetch(video_id, languages=["id", "en"])

        raw_text = " ".join([t.text for t in transcript_list])

        if len(raw_text.strip()) == 0:
            return jsonify({"error": "Transcript kosong atau tidak tersedia."}), 400

        # ===============================
        # AI PROMPTS
        # ===============================
        prompts = {
            "edukasi": f"Buat modul ajar SD dari materi berikut:\n{raw_text}",
            "kreator": f"Buat ide konten TikTok viral dari video berikut:\n{raw_text}",
            "bisnis": f"Buat copywriting bisnis yang menarik dari konten berikut:\n{raw_text}"
        }

        final_prompt = prompts.get(mode, f"Ringkas konten berikut:\n{raw_text}")

        # ===============================
        # GEMINI PROCESS
        # ===============================
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=final_prompt
        )

        result_text = response.text

        # Kurangi kredit
        users_db[user_id]["credits"] -= 1

        session["last_result"] = result_text

        return jsonify({
            "result": result_text,
            "remaining_credits": users_db[user_id]["credits"]
        })

    except Exception as e:
        return jsonify({"error": f"Gagal memproses: {str(e)}"}), 500


@app.route("/api/export-pdf")
def export_pdf():
    content = session.get("last_result")

    if not content:
        return jsonify({"error": "Tidak ada data untuk diekspor."}), 400

    filename = f"Hasil_{uuid.uuid4().hex[:6]}.pdf"
    file_path = create_pdf(content, filename)

    return send_file(file_path, as_attachment=True)


# ===============================
# RUN
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=False)
