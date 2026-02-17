from flask import Flask, render_template, request, jsonify, send_file, Response
import requests
import os
import uuid
import time
import threading
import json

app = Flask(__name__)

# Folder penyimpanan file sementara
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Database sederhana di memori untuk memantau progress
progress_db = {}

# === 📹 LOGGING SISTEM ===
@app.before_request
def log_request_info():
    if not request.path.startswith('/static') and not request.path.startswith('/api/progress'):
        print(f"LOG: {request.method} ke {request.path}", flush=True)

# --- CORE FUNCTION: COBALT API DOWNLOADER ---
def cobalt_worker(url, format_type, task_id):
    try:
        progress_db[task_id] = {"status": "starting", "percent": 5}
        
        # Konfigurasi API Cobalt (Mesin Downloader Luar)
        api_url = "https://api.cobalt.tools/api/json"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        payload = {
            "url": url,
            "vCodec": "h264", 
            "vQuality": "720",
            "isAudioOnly": True if format_type == 'mp3' else False,
            "filenameStyle": "basic"
        }

        print(f"Mengirim request API Cobalt untuk: {url}", flush=True)
        response = requests.post(api_url, json=payload, headers=headers, timeout=60)
        
        if response.status_code != 200:
            raise Exception(f"API Cobalt Error: {response.status_code}")

        data = response.json()
        if data.get('status') == 'error':
            raise Exception(data.get('text', 'Kesalahan API'))

        # Dapatkan link download langsung dari server Cobalt
        direct_link = data.get('url')
        print(f"Link download didapat: {direct_link}", flush=True)
        
        progress_db[task_id] = {"status": "downloading", "percent": 30}

        # Menarik file ke server Hugging Face agar user bisa download lokal
        file_resp = requests.get(direct_link, stream=True)
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
                        # Simulasi pergerakan bar progress (30% ke 95%)
                        p = 30 + (wrote / total_size * 65)
                        progress_db[task_id]["percent"] = round(p, 2)

        progress_db[task_id] = {
            "status": "finished", 
            "percent": 100, 
            "file_url": f"/api/get-file/{task_id}"
        }
        print(f"Download Berhasil: {task_id}", flush=True)

    except Exception as e:
        print(f"ERROR: {str(e)}", flush=True)
        progress_db[task_id] = {"status": "error", "error": str(e)}

# --- ENDPOINTS ---

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"error": "URL kosong!"}), 400
    
    # Memberikan info dummy agar tombol download di UI muncul
    return jsonify({
        "title": "Video Terdeteksi (API Mode)",
        "thumbnail": "https://placehold.co/600x400?text=Ready+To+Download",
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

# --- CLEANUP SYSTEM ---
def auto_delete_files():
    while True:
        now = time.time()
        try:
            for f in os.listdir(DOWNLOAD_FOLDER):
                filepath = os.path.join(DOWNLOAD_FOLDER, f)
                if os.path.isfile(filepath) and os.stat(filepath).st_mtime < now - 600:
                    os.remove(filepath)
        except: pass
        time.sleep(300)

threading.Thread(target=auto_delete_files, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=False, port=7860, host='0.0.0.0')