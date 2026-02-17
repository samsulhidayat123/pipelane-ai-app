from flask import Flask, render_template, request, jsonify, send_file, Response
import yt_dlp
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

# --- DEBUG & SETUP COOKIES ---
COOKIES_FILE = 'cookies.txt'
print("--- SYSTEM STARTUP ---")
if 'COOKIES_CONTENT' in os.environ:
    content = os.environ['COOKIES_CONTENT']
    # Cek apakah isi cookies valid (panjang karakter)
    if len(content) > 100:
        with open(COOKIES_FILE, 'w') as f:
            f.write(content)
        print(f"LOG: Berhasil membuat cookies.txt (Ukuran: {len(content)} bytes)")
    else:
        print("LOG ERROR: Isi Secret COOKIES_CONTENT terlalu pendek/kosong!")
else:
    print("LOG WARNING: Secret COOKIES_CONTENT tidak ditemukan!")
print("----------------------")

progress_db = {}

# --- FUNGSI OPTION YT-DLP YANG LEBIH KUAT ---
def get_ydl_opts(task_id=None, progress_hook=None):
    opts = {
        # 'impersonate' butuh library curl_cffi di requirements.txt
        'impersonate': 'chrome',
        
        # Cookie file
        'cookiefile': COOKIES_FILE if os.path.exists(COOKIES_FILE) else None,
        
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        
        # --- JURUS ANDALAN: MENYAMAR JADI ANDROID ---
        # Ini bypass paling ampuh buat server cloud (Hugging Face)
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['webpage', 'configs', 'js'],
                'innertube_client': ['android'],
            }
        },
        
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    if task_id:
        opts['outtmpl'] = os.path.join(DOWNLOAD_FOLDER, f"{task_id}.%(ext)s")
    
    if progress_hook:
        opts['progress_hooks'] = [progress_hook]

    return opts

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    if not data or not data.get('url'):
        return jsonify({"error": "URL tidak boleh kosong"}), 400

    url = data.get('url')
    # Pakai settingan yang sama kuatnya
    ydl_opts = get_ydl_opts()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                "title": info.get('title', 'Video Tanpa Judul'),
                "thumbnail": info.get('thumbnail'),
                "duration": info.get('duration_string', '00:00'),
                "platform": info.get('extractor_key', 'Platform'),
                "uploader": info.get('uploader', 'Kreator')
            })
    except Exception as e:
        print(f"INFO ERROR (Detailed): {str(e)}")
        # Kirim error asli ke frontend biar tau masalahnya apa
        return jsonify({"error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_task():
    data = request.json
    url = data.get('url')
    format_type = data.get('format', 'mp4')
    task_id = str(uuid.uuid4())
    progress_db[task_id] = {"status": "starting", "percent": 0}
    
    threading.Thread(target=run_yt_dlp, args=(url, format_type, task_id)).start()
    return jsonify({"task_id": task_id})

def run_yt_dlp(url, format_type, task_id):
    def progress_hook(d):
        if d['status'] == 'downloading':
            p_str = d.get('_percent_str', '0%').replace('%', '').strip()
            try:
                progress_db[task_id] = {
                    "status": "downloading", "percent": float(p_str),
                    "speed": d.get('_speed_str', 'N/A'), "eta": d.get('_eta_str', 'N/A')
                }
            except: pass
        elif d['status'] == 'finished':
            progress_db[task_id] = {"status": "processing", "percent": 100}

    # Ambil opsi dasar
    ydl_opts = get_ydl_opts(task_id, progress_hook)
    ydl_opts['noplaylist'] = True

    # Tambahan format
    if format_type == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]
        })
    else:
        ydl_opts.update({
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4'
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            progress_db[task_id] = {"status": "finished", "percent": 100, "file_url": f"/api/get-file/{task_id}"}
    except Exception as e:
        print(f"DOWNLOAD ERROR: {e}")
        progress_db[task_id] = {"status": "error", "error": str(e)}

# --- ROUTE LAINNYA TETAP SAMA ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/progress/<task_id>')
def progress_stream(task_id):
    def generate():
        while True:
            data = progress_db.get(task_id, {"status": "waiting", "percent": 0})
            yield f"data: {json.dumps(data)}\n\n"
            if data.get("status") in ["finished", "error"]:
                time.sleep(2)
                if task_id in progress_db: del progress_db[task_id]
                break
            time.sleep(0.5)
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/get-file/<task_id>')
def get_final_file(task_id):
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.startswith(task_id):
            target_file = os.path.join(DOWNLOAD_FOLDER, f)
            response = send_file(target_file, as_attachment=True)
            @response.call_on_close
            def cleanup():
                if os.path.exists(target_file): os.remove(target_file)
            return response
    return "File tidak ditemukan.", 404

def auto_delete_files():
    while True:
        now = time.time()
        try:
            if os.path.exists(DOWNLOAD_FOLDER):
                for f in os.listdir(DOWNLOAD_FOLDER):
                    filepath = os.path.join(DOWNLOAD_FOLDER, f)
                    if os.path.isfile(filepath) and os.stat(filepath).st_mtime < now - 600:
                        os.remove(filepath)
        except Exception as e: print(f"Error Cleanup: {e}")
        time.sleep(300)
threading.Thread(target=auto_delete_files, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=False, port=7860, host='0.0.0.0')