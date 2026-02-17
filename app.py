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

# Database sederhana untuk memantau progress di memori
progress_db = {}

# === 📹 LOGGING SISTEM ===
@app.before_request
def log_request_info():
    if not request.path.startswith('/static') and not request.path.startswith('/api/progress'):
        print(f"LOG: {request.method} ke {request.path}", flush=True)

# --- FUNGSI CORE: DOWNLOADER VIA COBALT API ---
def cobalt_worker(url, format_type, task_id):
    try:
        progress_db[task_id] = {"status": "starting", "percent": 5}
        
        # 1. Menghubungi API Cobalt
        api_url = "https://api.cobalt.tools/api/json"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Payload disesuaikan agar hasil download stabil
        payload = {
            "url": url,
            "vCodec": "h264", 
            "vQuality": "720",
            "isAudioOnly": True if format_type == 'mp3' else False,
            "filenameStyle": "basic"
        }

        print(f"Mengirim permintaan API untuk: {url}")
        response = requests.post(api_url, json=payload, headers=headers, timeout=60)
        
        if response.status_code != 200:
            raise Exception(f"API Error {response.status_code}")

        data = response.json()
        if data.get('status') == 'error':
            raise Exception(data.get('text', 'Kesalahan API'))

        # Link download langsung dari Cobalt
        direct_link = data.get('url')
        print(f"Link berhasil didapat: {direct_link}")
        
        progress_db[task_id] = {"status": "downloading", "percent": 30}

        # 2. Menarik file dari link Cobalt ke server Hugging Face
        # Ini dilakukan agar user mendownload langsung dari server kamu (lebih stabil)
        file_resp = requests.get(direct_link, stream=True)
        ext = 'mp3' if format_type == 'mp3' else 'mp4'
        filename = f"{task_id}.{ext}"
        filepath = os.path.join(DOWNLOAD_FOLDER, filename)

        total_size = int(file_resp.headers.get('content-length', 0))
        wrote = 0
        
        with open(filepath, 'wb') as f:
            for chunk in file_resp.iter_content(chunk_size=1024*1024): # 1MB per chunk
                if chunk:
                    f.write(chunk)
                    wrote += len(chunk)
                    if total_size > 0:
                        # Simulasi progress dari 30% ke 95%
                        p = 30 + (wrote / total_size * 65)
                        progress_db[task_id]["percent"] = round(p, 2)

        # 3. Selesai
        progress_db[task_id] = {
            "status": "finished", 
            "percent": 100, 
            "file_url": f"/api/get-file/{task_id}"
        }
        print(f"Download selesai untuk task: {task_id}")

    except Exception as e:
        print(f"ERROR WORKER: {str(e)}")
        progress_db[task_id] = {"status": "error", "error": f"Gagal: {str(e)}"}

# --- ENDPOINTS API ---

@app.route('/api/info', methods=['POST'])
def get_info():
    # Menyesuaikan dengan kebutuhan Frontend lama
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"error": "URL tidak boleh kosong"}), 400
    
    # Kita berikan info dummy yang sukses agar tombol download di frontend muncul
    return jsonify({
        "title": "Video Siap Diunduh",
        "thumbnail": "https://placehold.co/600x400?text=Video+Detected",
        "duration": "Bypass Mode",
        "uploader": "External API"
    })

@app.route('/api/download', methods=['POST'])
def download_task():
    data = request.json
    url = data.get('url')
    format_type = data.get('format', 'mp4')
    task_id = str(uuid.uuid4())
    
    # Jalankan proses download di background agar tidak timeout
    threading.Thread(target=cobalt_worker, args=(url, format_type, task_id)).start()
    
    return jsonify({"task_id": task_id})

@app.route('/api/progress/<task_id>')
def progress_stream(task_id):
    def generate():
        while True:
            # Mengambil status terbaru dari database memori
            data = progress_db.get(task_id, {"status": "waiting", "percent": 0})
            yield f"data: {json.dumps(data)}\n\n"
            
            # Berhenti jika sudah selesai atau error
            if data.get("status") in ["finished", "error"]:
                # Beri jeda sebentar sebelum menghapus task dari memori
                time.sleep(5)
                if task_id in progress_db:
                    del progress_db[task_id]
                break
            time.sleep(1) # Update setiap 1 detik
            
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/get-file/<task_id>')
def get_final_file(task_id):
    # Mencari file di folder downloads berdasarkan task_id
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.startswith(task_id):
            target_path = os.path.join(DOWNLOAD_FOLDER, f)
            return send_file(target_path, as_attachment=True)
    return "File tidak ditemukan atau sudah kadaluarsa.", 404

# --- MANAJEMEN PENYIMPANAN ---
def auto_delete_files():
    """Menghapus file yang sudah lebih dari 10 menit agar penyimpanan tidak penuh"""
    while True:
        now = time.time()
        try:
            for f in os.listdir(DOWNLOAD_FOLDER):
                filepath = os.path.join(DOWNLOAD_FOLDER, f)
                if os.path.isfile(filepath) and os.stat(filepath).st_mtime < now - 600:
                    os.remove(filepath)
                    print(f"Auto-deleted: {f}")
        except Exception as e:
            print(f"Error Cleanup: {e}")
        time.sleep(300) # Cek setiap 5 menit

threading.Thread(target=auto_delete_files, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # Menjalankan Flask di port 7860 untuk Hugging Face
    app.run(debug=False, port=7860, host='0.0.0.0')