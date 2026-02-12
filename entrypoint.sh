#!/bin/bash
set -e

# Fetch tracker list for aria2
tracker_list=$(curl -Ns https://ngosang.github.io/trackerslist/trackers_all_http.txt 2>/dev/null | awk '$0' | tr '\n\n' ',' || echo "")

# Start aria2c as daemon
aria2c --allow-overwrite=true --auto-file-renaming=true --bt-enable-lpd=true --bt-detach-seed-only=true \
    --bt-remove-unselected-file=true --bt-tracker="[$tracker_list]" --bt-max-peers=0 --enable-rpc=true \
    --rpc-max-request-size=1024M --max-connection-per-server=10 --max-concurrent-downloads=1000 --split=10 \
    --seed-ratio=0 --check-integrity=true --continue=true --daemon=true --disk-cache=40M --force-save=true \
    --min-split-size=10M --follow-torrent=mem --check-certificate=false --optimize-concurrent-downloads=true \
    --http-accept-gzip=true --max-file-not-found=0 --max-tries=20 --peer-id-prefix=-qB4520- --reuse-uri=true \
    --content-disposition-default-utf8=true --user-agent=Wget/1.12 --peer-agent=qBittorrent/4.5.2 --quiet=true \
    --summary-interval=0 --max-upload-limit=1K || echo "Warning: aria2c failed to start"

echo "[entrypoint] aria2c started"

# Start qBittorrent-nox with the project config profile
# --profile=/app makes qBittorrent look for config at /app/qBittorrent/config/qBittorrent.conf
# Generate PBKDF2 password hash for "adminadmin" and inject into config
python3 -c "
import hashlib, base64, os
salt = os.urandom(16)
dk = hashlib.pbkdf2_hmac('sha512', b'adminadmin', salt, 100000)
s = base64.b64encode(salt).decode()
d = base64.b64encode(dk).decode()
line = f'WebUI\\\Password_PBKDF2=@ByteArray({s}:{d})'
conf = '/app/qBittorrent/config/qBittorrent.conf'
with open(conf, 'r') as f:
    content = f.read()
if 'Password_PBKDF2' not in content:
    content = content.rstrip() + '\n' + line + '\n'
    with open(conf, 'w') as f:
        f.write(content)
    print(f'[entrypoint] Set qBittorrent password hash')
else:
    print(f'[entrypoint] qBittorrent password hash already set')
"
qbittorrent-nox --webui-port=8090 --confirm-legal-notice --profile=/app -d || echo "Warning: qbittorrent-nox failed to start"
echo "[entrypoint] qbittorrent-nox started"

# Start mega-cmd-server (needed for mega-login, mega-get, etc.)
mega-cmd-server &
echo "[entrypoint] mega-cmd-server started"

# Wait for services to be ready
sleep 3

# Start the bot
exec python -m bot
