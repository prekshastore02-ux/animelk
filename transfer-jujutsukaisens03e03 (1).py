# ANIMELK local transfer script — run on YOUR machine (no Colab needed).
# Requires:  pip install requests boto3   +   ffmpeg/ffprobe in PATH (winget install ffmpeg)
#            https://ffmpeg.org/download.html

import requests, os, sys, json, subprocess

VIDEO_URL = "https://rd17.seedr.cc/ff_get/3756187/5998605363/JUJUTSU%20KAISEN%20S03E05%20Passion%201080p%20CR%20WEB-DL%20DDP2%200%20H%20264-Kitsune.mkv?st=cfqfJOaBfZBDEq-q0jebmQ&e=1790682788"
FILENAME = "jujutsukaisens03e03"
R2_ENDPOINT = "https://6a6c30d852355720999f951c39dbb52f.r2.cloudflarestorage.com"
R2_BUCKET = "animelk"
R2_PUBLIC = "https://pub-6ff0f5498bfd4384af30166867d46d8d.r2.dev"
R2_ACCESS_KEY = "e1656e8eaaadccdc7e49046a85cf6483"
R2_SECRET_KEY = "89d323c21e18338e6955eeb1ee99a117bfd5e90cd4d61a6296bb52b20aa60f89"
ABYSS_KEY = "855db2dc010eb12885aec4daf49f42f7"
ABYSS_ENDPOINT = "https://api.abyss.to/api/upload/url"

# ---------- 1) download ----------
print('downloading from:', VIDEO_URL)
r = requests.get(VIDEO_URL, stream=True, timeout=600, headers={'User-Agent': 'Mozilla/5.0'})
r.raise_for_status()
total = int(r.headers.get('content-length') or 0)
done = 0
with open('video.bin', 'wb') as f:
    for chunk in r.iter_content(2 * 1024 * 1024):
        f.write(chunk)
        done += len(chunk)
        if total:
            print(f'  downloaded {done/1e6:.1f}/{total/1e6:.1f} MB', end='\r')
print()
print(f'download complete: {os.path.getsize("video.bin")/1e6:.1f} MB')

# ---------- 2) container/audio fix (MKV -> MP4, DDP -> AAC) ----------
def ensure_ffmpeg():
    if subprocess.run(['ffmpeg', '-version'], capture_output=True).returncode == 0:
        return
    print('ffmpeg not found — installing...')
    if sys.platform.startswith('linux'):
        r = subprocess.run(['sudo', 'apt-get', 'install', '-y', 'ffmpeg'], capture_output=True)
        if r.returncode != 0:
            print('auto-install failed, run manually:  sudo apt-get update && sudo apt-get install -y ffmpeg')
            sys.exit(1)
    elif sys.platform == 'win32':
        print('Install ffmpeg first:  winget install ffmpeg   (or https://ffmpeg.org/download.html)')
        sys.exit(1)
    else:
        print('Install ffmpeg from https://ffmpeg.org/download.html')
        sys.exit(1)
    if subprocess.run(['ffmpeg', '-version'], capture_output=True).returncode != 0:
        print('ffmpeg still not available')
        sys.exit(1)
    print('ffmpeg ready')

ensure_ffmpeg()
probe = subprocess.run(
    ['ffprobe', '-v', 'error', '-show_entries', 'format=format_name:stream=codec_name,codec_type', '-of', 'json', 'video.bin'],
    capture_output=True, text=True)
try:
    info = json.loads(probe.stdout)
    fmt = info.get('format', {}).get('format_name', '')
    audio_codecs = [s.get('codec_name') for s in info.get('streams', []) if s.get('codec_type') == 'audio']
except Exception:
    fmt, audio_codecs = '', []
print('container:', fmt or '(unknown)', '| audio:', audio_codecs)
is_mp4 = 'mp4' in fmt
audio_ok = all(c in ('aac', 'mp3') for c in audio_codecs) if audio_codecs else True
if not (is_mp4 and audio_ok):
    print('remuxing to MP4 + AAC...')
    conv = subprocess.run(
        ['ffmpeg', '-y', '-i', 'video.bin', '-map', '0:v:0', '-map', '0:a?',
         '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', 'video.fixed.mp4'],
        capture_output=True)
    if conv.returncode != 0:
        print(conv.stderr.decode()[-600:])
        sys.exit(1)
    os.replace('video.fixed.mp4', 'video.bin')
    print('fixed: MP4 + AAC')

# ---------- 3) upload to Cloudflare R2 ----------
try:
    import boto3
    from boto3.s3.transfer import TransferConfig
except ImportError:
    print('installing boto3...')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'boto3'], check=True)
    import boto3
    from boto3.s3.transfer import TransferConfig

s3 = boto3.client('s3', endpoint_url=R2_ENDPOINT, aws_access_key_id=R2_ACCESS_KEY,
                  aws_secret_access_key=R2_SECRET_KEY, region_name='auto')
cfg = TransferConfig(multipart_threshold=8*1024*1024, multipart_chunksize=8*1024*1024,
                     max_concurrency=16, use_threads=True)
print('uploading to R2...')
s3.upload_file('video.bin', R2_BUCKET, FILENAME, ExtraArgs={'ContentType': 'video/mp4'}, Config=cfg)
print('R2 DONE:', R2_PUBLIC + '/' + FILENAME)
DIRECT_URL = R2_PUBLIC + '/' + FILENAME

# ---------- 4) remote upload to abyss.to ----------
payload = {'key': ABYSS_KEY, 'url': DIRECT_URL}
r = requests.post(ABYSS_ENDPOINT, data=payload, timeout=600)
if r.status_code in (400, 404, 405):
    r = requests.get(ABYSS_ENDPOINT, params=payload, timeout=600)
print('abyss status:', r.status_code)
try:
    resp = r.json()
except Exception:
    resp = {'raw': r.text[:1000]}
print(json.dumps(resp, indent=2)[:2000])

def find_slug(obj, depth=0):
    if depth > 4:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and 7 <= len(v) <= 17 and v.replace('-', '').replace('_', '').isalnum() and k.lower() in ('slug', 'id', 'code', 'file_code', 'filecode'):
                return v
            found = find_slug(v, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_slug(v, depth + 1)
            if found:
                return found
    return None

slug = find_slug(resp)
if slug:
    print('ABYSS DONE — EMBED URL: https://player.abyssplayer.com/' + slug)
else:
    print('Could not auto-detect the new video id - copy it from the response above.')

print('ALL DONE')
os.remove('video.bin')