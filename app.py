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

# Database sederhana di memori untuk menyimpan status progress per Task ID
progress_db = {}

# --- SISTEM PEMBERSIHAN OTOMATIS (Background Task) ---
def auto_delete_files():
    """Menghapus file yang berumur lebih dari 10 menit agar server tidak penuh."""
    while True:
        now = time.time()
        try:
            if os.path.exists(DOWNLOAD_FOLDER):
                for f in os.listdir(DOWNLOAD_FOLDER):
                    filepath = os.path.join(DOWNLOAD_FOLDER, f)
                    # Jika file lebih tua dari 600 detik (10 menit), hapus.
                    if os.path.isfile(filepath) and os.stat(filepath).st_mtime < now - 600:
                        os.remove(filepath)
        except Exception as e:
            print(f"Error Cleanup: {e}")
        time.sleep(300) # Cek setiap 5 menit

# Jalankan cleaner di thread terpisah
threading.Thread(target=auto_delete_files, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

# --- SSE ENDPOINT: Progress Real-time ---
@app.route('/api/progress/<task_id>')
def progress_stream(task_id):
    def generate():
        while True:
            data = progress_db.get(task_id, {"status": "waiting", "percent": 0})
            yield f"data: {json.dumps(data)}\n\n"
            
            if data.get("status") == "finished" or data.get("status") == "error":
                time.sleep(2)
                # Bersihkan memory DB setelah selesai
                if task_id in progress_db:
                    del progress_db[task_id]
                break
            time.sleep(0.5) 
            
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    if not data or not data.get('url'):
        return jsonify({"error": "URL tidak boleh kosong"}), 400

    url = data.get('url')
    ydl_opts = {'quiet': True, 'no_warnings': True}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                "title": info.get('title', 'Video'),
                "thumbnail": info.get('thumbnail'),
                "duration": info.get('duration_string', '00:00'),
                "platform": info.get('extractor_key', 'Platform'),
                "uploader": info.get('uploader', 'Kreator')
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_task():
    data = request.json
    url = data.get('url')
    format_type = data.get('format', 'mp4')
    task_id = str(uuid.uuid4())
    
    progress_db[task_id] = {"status": "starting", "percent": 0}
    thread = threading.Thread(target=run_yt_dlp, args=(url, format_type, task_id))
    thread.start()
    return jsonify({"task_id": task_id})

def run_yt_dlp(url, format_type, task_id):
    output_tmpl = os.path.join(DOWNLOAD_FOLDER, f"{task_id}.%(ext)s")

    def progress_hook(d):
        if d['status'] == 'downloading':
            p_str = d.get('_percent_str', '0%').replace('%', '').strip()
            try:
                progress_db[task_id] = {
                    "status": "downloading", 
                    "percent": float(p_str),
                    "speed": d.get('_speed_str', 'N/A'),
                    "eta": d.get('_eta_str', 'N/A')
                }
            except: pass
        elif d['status'] == 'finished':
            progress_db[task_id] = {"status": "processing", "percent": 100}

    ydl_opts = {
        'impersonate': 'chrome',
        'outtmpl': output_tmpl,
        'quiet': True,
        'progress_hooks': [progress_hook],
        'noplaylist': True,
    }

    # Logika Format (MP3 / MP4)
    if format_type == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        ydl_opts.update({
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4'
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            progress_db[task_id] = {
                "status": "finished", 
                "percent": 100, 
                "file_url": f"/api/get-file/{task_id}"
            }
    except Exception as e:
        progress_db[task_id] = {"status": "error", "error": str(e)}

@app.route('/api/get-file/<task_id>')
def get_final_file(task_id):
    """Mengirim file ke user, lalu menghapusnya setelah transfer selesai."""
    target_file = None
    # Cari file yang namanya diawali dengan task_id
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.startswith(task_id):
            target_file = os.path.join(DOWNLOAD_FOLDER, f)
            break

    if target_file and os.path.exists(target_file):
        response = send_file(target_file, as_attachment=True)
        
        # TRIK AMAN: Fungsi ini dijalankan otomatis saat koneksi download ditutup
        @response.call_on_close
        def cleanup():
            try:
                if os.path.exists(target_file):
                    os.remove(target_file)
            except Exception as e:
                print(f"Gagal menghapus {target_file}: {e}")
        
        return response
    
    return "File tidak ditemukan atau sudah kedaluwarsa.", 404

if __name__ == '__main__':
    # Debug=True di lokal, tapi Gunicorn akan pakai setting sendiri
    app.run(debug=True, port=5000, host='0.0.0.0')