from flask import Flask, render_template, request, jsonify, send_file, Response
import requests
import os
import uuid
import time
import threading
import json

app = Flask(__name__)

DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

progress_db = {}

# --- FUNGSI CORE: COBALT API v10 WORKER ---
def cobalt_worker(url, format_type, task_id):
    try:
        progress_db[task_id] = {"status": "starting", "percent": 10}
        
        # 1. Pilih Instance Cobalt v10 yang Aktif
        # Kamu bisa ganti ke: https://co.wuk.sh/ atau instance lain dari cobalt.best
        api_url = "https://api.cobalt.tools/" 
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # 2. Payload SESUAI STANDAR v10 (Ganti keys lama ke baru)
        payload = {
            "url": url,
            "videoQuality": "720",      # Dulu vQuality
            "audioFormat": "mp3",       # Dulu aFormat
            "downloadMode": "audio" if format_type == 'mp3' else "auto", # Dulu isAudioOnly
            "filenameStyle": "basic",
            "youtubeVideoCodec": "h264"
        }

        print(f"Mencoba tembus lewat API v10: {api_url}")
        resp = requests.post(api_url, json=payload, headers=headers, timeout=60)
        
        if resp.status_code != 200:
            print(f"Detail Error: {resp.text}")
            raise Exception(f"API Error {resp.status_code}")

        data = resp.json()
        
        # Cobalt v10 biasanya mengembalikan status 'tunnel' atau 'redirect'
        if 'url' not in data:
            raise Exception(f"API tidak memberikan link: {data.get('text', 'Unknown')}")

        download_link = data['url']
        progress_db[task_id] = {"status": "downloading", "percent": 40}

        # 3. Download File ke Server Kita
        file_resp = requests.get(download_link, stream=True)
        ext = 'mp3' if format_type == 'mp3' else 'mp4'
        filepath = os.path.join(DOWNLOAD_FOLDER, f"{task_id}.{ext}")

        total_size = int(file_resp.headers.get('content-length', 0))
        wrote = 0
        with open(filepath, 'wb') as f:
            for chunk in file_resp.iter_content(chunk_size=1024*1024):
                f.write(chunk)
                wrote += len(chunk)
                if total_size > 0:
                    p = 40 + (wrote / total_size * 55)
                    progress_db[task_id]["percent"] = round(p, 2)

        progress_db[task_id] = {"status": "finished", "percent": 100, "file_url": f"/api/get-file/{task_id}"}

    except Exception as e:
        print(f"❌ API v10 ERROR: {str(e)}")
        progress_db[task_id] = {"status": "error", "error": str(e)}

@app.route('/api/info', methods=['POST'])
def get_info():
    return jsonify({
        "title": "Ready to Download (v10 API)",
        "thumbnail": "https://placehold.co/600x400?text=v10+API+Active",
        "duration": "Stable Mode",
        "uploader": "Cobalt Community"
    })

@app.route('/api/download', methods=['POST'])
def download_task():
    data = request.json
    url = data.get('url')
    format_type = data.get('format', 'mp4')
    task_id = str(uuid.uuid4())
    progress_db[task_id] = {"status": "starting", "percent": 0}
    threading.Thread(target=cobalt_worker, args=(url, format_type, task_id)).start()
    return jsonify({"task_id": task_id})

# --- ROUTE STANDAR (TETAP SAMA) ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/progress/<task_id>')
def progress_stream(task_id):
    def generate():
        while True:
            data = progress_db.get(task_id, {"status": "waiting", "percent": 0})
            yield f"data: {json.dumps(data)}\n\n"
            if data.get("status") in ["finished", "error"]: break
            time.sleep(1)
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/get-file/<task_id>')
def get_final_file(task_id):
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.startswith(task_id):
            return send_file(os.path.join(DOWNLOAD_FOLDER, f), as_attachment=True)
    return "File missing.", 404

if __name__ == '__main__':
    app.run(debug=False, port=7860, host='0.0.0.0')