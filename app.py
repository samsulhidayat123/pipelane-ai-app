from flask import Flask, render_template, request, jsonify, send_file, Response
import requests
import os
import uuid
import time
import threading
import json
import re

app = Flask(__name__)

# Folder penyimpanan file sementara
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

progress_db = {}

# --- FUNGSI MEMBERSIHKAN URL (Hapus Tracker) ---
def clean_url(url):
    # Menghapus tracker seperti ?si= atau &feature= agar API tidak bingung
    cleaned = url.split('?')[0]
    # Jika link youtube biasa (watch?v=), ambil v= nya saja
    if "youtube.com/watch" in url:
        v_param = re.search(r"v=([a-zA-Z0-9_-]+)", url)
        if v_param:
            return f"https://www.youtube.com/watch?v={v_param.group(1)}"
    return cleaned

# --- CORE FUNCTION: COBALT API (FIXED 400) ---
def cobalt_worker(url, format_type, task_id):
    try:
        progress_db[task_id] = {"status": "starting", "percent": 5}
        
        # 1. Bersihkan URL dulu
        target_url = clean_url(url)
        print(f"URL Dibersihkan: {target_url}", flush=True)

        # 2. Konfigurasi API Cobalt
        api_url = "https://api.cobalt.tools/api/json"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # Payload yang lebih kompatibel
        payload = {
            "url": target_url,
            "vCodec": "h264",
            "vQuality": "720", # Pastikan string, bukan angka murni
            "isAudioOnly": True if format_type == 'mp3' else False,
            "filenameStyle": "basic"
        }

        print(f"Mengirim request ke API Cobalt...", flush=True)
        response = requests.post(api_url, json=payload, headers=headers, timeout=60)
        
        # LOGGING ERROR DETAILED
        if response.status_code != 200:
            error_msg = response.text
            print(f"❌ API Error {response.status_code}: {error_msg}", flush=True)
            raise Exception(f"API Cobalt menolak request (Code: {response.status_code})")

        data = response.json()
        if data.get('status') == 'error':
            raise Exception(data.get('text', 'Kesalahan Internal API'))

        direct_link = data.get('url')
        print(f"✅ Link didapat: {direct_link}", flush=True)
        
        progress_db[task_id] = {"status": "downloading", "percent": 30}

        # 3. Proses Download File
        file_resp = requests.get(direct_link, stream=True, timeout=120)
        ext = 'mp3' if format_type == 'mp3' else 'mp4'
        filepath = os.path.join(DOWNLOAD_FOLDER, f"{task_id}.{ext}")

        total_size = int(file_resp.headers.get('content-length', 0))
        wrote = 0
        
        with open(filepath, 'wb') as f:
            for chunk in file_resp.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
                    wrote += len(chunk)
                    if total_size > 0:
                        p = 30 + (wrote / total_size * 65)
                        progress_db[task_id]["percent"] = round(p, 2)

        progress_db[task_id] = {
            "status": "finished", 
            "percent": 100, 
            "file_url": f"/api/get-file/{task_id}"
        }

    except Exception as e:
        print(f"ERROR: {str(e)}", flush=True)
        progress_db[task_id] = {"status": "error", "error": str(e)}

# --- ENDPOINTS ---
@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    url = data.get('url')
    if not url: return jsonify({"error": "URL kosong!"}), 400
    return jsonify({
        "title": "Video Siap Diunduh",
        "thumbnail": "https://placehold.co/600x400?text=API+Mode+Active",
        "duration": "Bypass Mode",
        "uploader": "External API"
    })

@app.route('/api/download', methods=['POST'])
def download_task():
    data = request.json
    url = data.get('url')
    format_type = data.get('format', 'mp4')
    task_id = str(uuid.uuid4())
    threading.Thread(target=cobalt_worker, args=(url, format_type, task_id)).start()
    return jsonify({"task_id": task_id})

@app.route('/api/progress/<task_id>')
def progress_stream(task_id):
    def generate():
        while True:
            data = progress_db.get(task_id, {"status": "waiting", "percent": 0})
            yield f"data: {json.dumps(data)}\n\n"
            if data.get("status") in ["finished", "error"]:
                time.sleep(5)
                if task_id in progress_db: del progress_db[task_id]
                break
            time.sleep(1)
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/get-file/<task_id>')
def get_final_file(task_id):
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.startswith(task_id):
            return send_file(os.path.join(DOWNLOAD_FOLDER, f), as_attachment=True)
    return "File tidak ditemukan.", 404

@app.route('/')
def index(): return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=False, port=7860, host='0.0.0.0')