# === ☢️ DNS MANUAL PATCH (ANTARA HIDUP & MATI) ===
import socket
try:
    import dns.resolver
    def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        try:
            return original_getaddrinfo(host, port, family, type, proto, flags)
        except socket.gaierror:
            print(f"⚠️ DNS Error untuk {host}, mencoba manual resolve...", flush=True)
            try:
                resolver = dns.resolver.Resolver()
                resolver.nameservers = ['8.8.8.8', '1.1.1.1']
                answers = resolver.resolve(host, 'A')
                ip = answers[0].to_text()
                print(f"✅ Berhasil resolve manual: {host} -> {ip}", flush=True)
                return [(socket.AF_INET, type, proto, '', (ip, port))]
            except Exception as e:
                print(f"❌ Gagal total resolve manual: {e}", flush=True)
                raise
    original_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = custom_getaddrinfo
except ImportError:
    print("⚠️ Warning: dnspython belum terinstall.")

from flask import Flask, render_template, request, jsonify, send_file, Response
import yt_dlp
import os
import uuid
import time
import threading
import json

app = Flask(__name__)

# === 📹 LOGGING REQUEST ===
@app.before_request
def log_request_info():
    if not request.path.startswith('/static') and not request.path.startswith('/api/progress'):
        print(f"LOG: {request.method} {request.path}", flush=True)

DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# --- SETUP COOKIES ---
COOKIES_FILE = 'cookies.txt'
if 'COOKIES_CONTENT' in os.environ:
    with open(COOKIES_FILE, 'w') as f:
        f.write(os.environ['COOKIES_CONTENT'])
    print("LOG: Cookies dimuat dari Secret.")

progress_db = {}

def get_ydl_opts(task_id=None, progress_hook=None):
    return {
        'cookiefile': COOKIES_FILE if os.path.exists(COOKIES_FILE) else None,
        'quiet': False,
        'no_warnings': False,
        'verbose': True,
        'force_ipv4': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'socket_timeout': 30,
        
        # === JURUS ANTI-RELOAD (TV & VR CLIENT) ===
        # Client ini paling kebal terhadap proteksi "Reload Page" YouTube
        'extractor_args': {
            'youtube': {
                'player_client': ['tvhtml5', 'android_vr'],
                'player_skip': ['webpage', 'configs', 'js']
            }
        },
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        },
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, f"{task_id}.%(ext)s") if task_id else None,
        'progress_hooks': [progress_hook] if progress_hook else []
    }

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    url = data.get('url')
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            # Metadata fetch
            info = ydl.extract_info(url, download=False)
            return jsonify({
                "title": info.get('title', 'Video'),
                "thumbnail": info.get('thumbnail'),
                "duration": info.get('duration_string', '00:00'),
                "uploader": info.get('uploader', 'Kreator')
            })
    except Exception as e:
        print(f"❌ INFO ERROR: {str(e)}", flush=True)
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
    def hook(d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('%', '').strip()
            try: progress_db[task_id] = {"status": "downloading", "percent": float(p)}
            except: pass
        elif d['status'] == 'finished':
            progress_db[task_id] = {"status": "processing", "percent": 100}

    opts = get_ydl_opts(task_id, hook)
    
    # Ambil 'best' saja untuk meminimalisir SABR throttling
    if format_type == 'mp3':
        opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]})
    else:
        opts.update({'format': 'best[ext=mp4]/best', 'merge_output_format': 'mp4'})

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
            progress_db[task_id] = {"status": "finished", "percent": 100, "file_url": f"/api/get-file/{task_id}"}
    except Exception as e:
        print(f"❌ DOWNLOAD ERROR: {str(e)}", flush=True)
        progress_db[task_id] = {"status": "error", "error": str(e)}

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
    return "File tidak ditemukan.", 404

def auto_delete():
    while True:
        now = time.time()
        for f in os.listdir(DOWNLOAD_FOLDER):
            p = os.path.join(DOWNLOAD_FOLDER, f)
            if os.path.isfile(p) and os.stat(p).st_mtime < now - 600: os.remove(p)
        time.sleep(300)

threading.Thread(target=auto_delete, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=False, port=7860, host='0.0.0.0')