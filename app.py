# === ☢️ DNS MANUAL PATCH (WAJIB PALING ATAS) ===
# Memaksa server Hugging Face pakai DNS Google biar gak tersesat (Errno -5)
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
    print("⚠️ Warning: dnspython belum terinstall, patch DNS dilewati.")
# ===============================================

from flask import Flask, render_template, request, jsonify, send_file, Response
import yt_dlp
import os
import uuid
import time
import threading
import json

app = Flask(__name__)

# === 📹 CCTV LOGGING ===
@app.before_request
def log_request_info():
    if not request.path.startswith('/static') and not request.path.startswith('/api/progress'):
        print(f"LOG MASUK: {request.method} ke {request.path}", flush=True)
    if request.method == 'POST' and request.is_json:
        print(f"LOG DATA: {request.get_json()}", flush=True)

# Folder penyimpanan file sementara
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# --- SETUP COOKIES ---
COOKIES_FILE = 'cookies.txt'
if 'COOKIES_CONTENT' in os.environ:
    with open(COOKIES_FILE, 'w') as f:
        f.write(os.environ['COOKIES_CONTENT'])
    print(f"LOG: Cookies berhasil dimuat dari Secret.")
else:
    print("LOG WARNING: Secret COOKIES_CONTENT tidak ditemukan!")

progress_db = {}

# --- FUNGSI OPTION YT-DLP (VERSI STABIL) ---
def get_ydl_opts(task_id=None, progress_hook=None):
    opts = {
        'cookiefile': COOKIES_FILE if os.path.exists(COOKIES_FILE) else None,
        'quiet': False,
        'no_warnings': False,
        'verbose': True,
        'force_ipv4': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'socket_timeout': 30,
        
        # Jurus Menyamar jadi Android (Paling ampuh buat bypass bot-check)
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['webpage', 'configs', 'js'],
                'innertube_client': ['android'],
            }
        },
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36',
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
    ydl_opts = get_ydl_opts()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Metadata fetch
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

    ydl_opts = get_ydl_opts(task_id, progress_hook)
    ydl_opts['noplaylist'] = True

    # --- PENGATURAN FORMAT YANG LEBIH LENTUR (ANTI-ERROR) ---
    if format_type == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]
        })
    else:
        ydl_opts.update({
            # Ambil video dan audio terbaik tanpa memandang ekstensi asli, gabung jadi MP4
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4'
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            progress_db[task_id] = {"status": "finished", "percent": 100, "file_url": f"/api/get-