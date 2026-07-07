# 🔐 WireGuard Peer Generation API

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-black?logo=flask&logoColor=white)
![WireGuard](https://img.shields.io/badge/WireGuard-VPN-88171A?logo=wireguard&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-Ubuntu-E95420?logo=ubuntu&logoColor=white)
![systemd](https://img.shields.io/badge/systemd-service-green)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

A lightweight, self-hosted REST API that generates a **fresh WireGuard client configuration on every request** — new keypair, new preshared key, and the next free IP — while automatically picking up all server settings (endpoint, DNS, AllowedIPs, MTU, keepalive) from an existing [wireguard-manager](https://github.com/complexorganizations/wireguard-manager) installation. No values are hardcoded.

Built and deployed on a 1.9 GB RAM DigitalOcean VPS as part of a hands-on DevOps lab.

---

## 📖 Table of Contents

- [What This Project Does](#-what-this-project-does)
- [Features](#-features)
- [Directory Structure](#-directory-structure)
- [How It Works](#-how-it-works)
- [Installation & Usage](#-installation--usage)
- [API Reference](#-api-reference)
- [Distributing Configs to Users](#-distributing-configs-to-users)
- [Troubleshooting Notes](#-troubleshooting-notes)
- [Security Considerations](#-security-considerations)
- [License](#-license)

---

## 🎯 What This Project Does

Manually adding a WireGuard peer means generating keys, editing `wg0.conf`, picking a free IP, running `wg set`, and writing a client config by hand — every single time. This API automates the entire flow behind a single authenticated HTTP endpoint:

```
GET http://<server-ip>:5002/wg-config?token=<API_TOKEN>
```

One request returns a complete, ready-to-import client configuration in plain text. Every response is unique — each caller gets their own peer identity.

## ✨ Features

- 🔑 **Fresh cryptography per request** — new private key, public key, and preshared key generated with the official `wg` tooling on every call
- 📡 **Zero hardcoded settings** — endpoint, DNS servers, AllowedIPs, MTU, and keepalive are parsed live from the wireguard-manager header line in `wg0.conf`
- 🔢 **Automatic IP allocation** — scans existing peers and assigns the next free host address (and reuses gaps left by deleted peers)
- ⚡ **Live peer activation** — new peers are added to the running interface with `wg set`, no restart or downtime
- 🗂 **wireguard-manager compatible** — peers are appended using the same `# <id> start / end` comment convention, so the original manager script keeps working
- 🔒 **Token authentication** — requests without a valid `?token=` query parameter receive `403 Forbidden`
- 🧵 **Thread-safe writes** — a lock guards `wg0.conf` so concurrent requests cannot corrupt the file
- 🖥 **systemd managed** — runs as a service with auto-restart and a `MemoryMax` cap for low-RAM VPS environments
- 🌐 **CORS enabled** — the endpoint can be consumed directly from browser-based frontends

## 📁 Directory Structure

```
/opt/wg-api/
├── wg_api.py              # The Flask API (main script)
└── venv/                  # Isolated Python virtual environment
    └── ...                # flask, flask-cors and dependencies

/etc/wireguard/
├── wg0.conf               # Server config (read + appended by the API)
└── clients/               # One saved .conf per generated peer
    ├── <peer-id>-wg0.conf
    └── ...

/etc/systemd/system/
└── wg-api.service         # systemd unit (auto-start, restart, memory cap)

/root/
└── wg-api-token.txt       # API token (chmod 600, root-only)
```

## ⚙️ How It Works

```
Client request                     Flask API (port 5002)                WireGuard
──────────────                     ─────────────────────                ─────────
GET /wg-config?token=...  ──────►  1. Validate token (403 if wrong)
                                   2. Read /etc/wireguard/wg0.conf
                                   3. Parse header line
                                      (subnet, endpoint, pubkey,
                                       DNS, MTU, keepalive, AllowedIPs)
                                   4. Find next free IP
                                      (scan existing AllowedIPs)
                                   5. wg genkey / wg pubkey / wg genpsk
                                   6. Append [Peer] block to wg0.conf
                                   7. wg set wg0 peer ...       ──────► Peer live
                                   8. Save copy to clients/                instantly
◄──────  9. Return client config
         (text/plain)
```

The key design decision: **the wireguard-manager header line is the single source of truth.** The first comment line of `wg0.conf` contains every value a client needs:

```
# <v4-subnet> <v6-subnet> <endpoint> <server-pubkey> <dns> <mtu> <keepalive> <allowed-ips>
```

The API splits this line and builds the client config from it — so if the server settings ever change through wireguard-manager, the API picks them up automatically on the next request.

## 🚀 Installation & Usage

### Prerequisites

- Ubuntu server with WireGuard installed via [wireguard-manager](https://github.com/complexorganizations/wireguard-manager)
- An active `wg0` interface (`systemctl status wg-quick@wg0`)
- Python 3.10+ with `python3-venv`
- Root access

### 1. Set up the environment

```bash
sudo mkdir -p /opt/wg-api
sudo python3 -m venv /opt/wg-api/venv
sudo /opt/wg-api/venv/bin/pip install flask flask-cors
```

### 2. Deploy the script

Copy `wg_api.py` (below) to `/opt/wg-api/wg_api.py`, then:

```bash
sudo chmod 700 /opt/wg-api/wg_api.py
```

### 3. Generate and set your API token

```bash
NEW_TOKEN=$(openssl rand -hex 16)
sudo sed -i "s/CHANGE_ME_TOKEN/$NEW_TOKEN/" /opt/wg-api/wg_api.py
echo "$NEW_TOKEN" | sudo tee /root/wg-api-token.txt > /dev/null
sudo chmod 600 /root/wg-api-token.txt
unset NEW_TOKEN
```

The token is saved to `/root/wg-api-token.txt` — it never prints to the screen.

### 4. Install the systemd service

Create `/etc/systemd/system/wg-api.service`:

```ini
[Unit]
Description=WireGuard Config Generator API
After=network.target wg-quick@wg0.service

[Service]
Type=simple
ExecStart=/opt/wg-api/venv/bin/python /opt/wg-api/wg_api.py
Restart=on-failure
RestartSec=5
MemoryMax=150M

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wg-api.service
sudo systemctl status wg-api.service
```

### 5. Test

```bash
# With a valid token → full client config
curl "http://127.0.0.1:5002/wg-config?token=$(sudo cat /root/wg-api-token.txt)"

# Without a token → 403 Forbidden
curl -i http://127.0.0.1:5002/wg-config
```

## 📜 The API Script

`/opt/wg-api/wg_api.py`:

```python
#!/usr/bin/env python3
"""WireGuard config generator API — all settings picked up from wg0.conf."""

import ipaddress
import secrets
import subprocess
import tempfile
import threading
import os

from flask import Flask, Response, request, abort
from flask_cors import CORS

WG_CONF = "/etc/wireguard/wg0.conf"
CLIENTS_DIR = "/etc/wireguard/clients"
WG_INTERFACE = "wg0"
API_TOKEN = "CHANGE_ME_TOKEN"  # replaced during setup (step 3)

app = Flask(__name__)
CORS(app)
lock = threading.Lock()  # prevents concurrent writes corrupting wg0.conf


def run(cmd, input_text=None):
    """Run a shell command, return stdout, raise with stderr on failure."""
    result = subprocess.run(
        cmd, input=input_text, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


def parse_header(conf_text):
    """Extract all settings from the wireguard-manager header line.

    Format: # <v4subnet> <v6subnet> <endpoint> <serverpubkey> <dns> <mtu> <keepalive> <allowedips>
    """
    first_line = conf_text.splitlines()[0]
    parts = first_line.lstrip("#").split()
    return {
        "v4_subnet": parts[0],       # e.g. 12.0.0.0/8
        "v6_subnet": parts[1],       # e.g. fd00:00:00::0/8
        "endpoint": parts[2],        # e.g. 1.2.3.4:51820
        "server_pubkey": parts[3],
        "dns": parts[4],
        "mtu": parts[5],             # client MTU
        "keepalive": parts[6],
        "allowed_ips": parts[7],     # e.g. 0.0.0.0/0,::/0
    }


def next_free_host(conf_text, v4_subnet):
    """Scan existing peers' AllowedIPs and return the next free host number."""
    used = set()
    for line in conf_text.splitlines():
        line = line.strip()
        if line.startswith("AllowedIPs") and "/32" in line:
            ip_part = line.split("=")[1].split(",")[0].strip()  # 12.0.0.2/32
            ip = ipaddress.ip_address(ip_part.split("/")[0])
            used.add(int(ip) & 0xFF)  # last octet
    host = 2
    while host in used:
        host += 1
    if host > 254:
        raise RuntimeError("Subnet full: no free IP available")
    return host


@app.route("/wg-config", methods=["GET"])
def wg_config():
    if request.args.get("token") != API_TOKEN:
        abort(403)
    with lock:
        with open(WG_CONF, "r") as f:
            conf_text = f.read()

        settings = parse_header(conf_text)

        # --- Allocate the next free IP ---
        host = next_free_host(conf_text, settings["v4_subnet"])
        base_v4 = settings["v4_subnet"].split("/")[0].rsplit(".", 1)[0]
        client_v4 = f"{base_v4}.{host}"
        v6_prefix = settings["v6_subnet"].split("/")[0].rsplit("::", 1)[0]
        client_v6 = f"{v6_prefix}::{host}"

        # --- Fresh keys on every request ---
        client_priv = run(["wg", "genkey"])
        client_pub = run(["wg", "pubkey"], input_text=client_priv)
        psk = run(["wg", "genpsk"])

        # --- Peer ID (same random-hex style as wireguard-manager) ---
        peer_id = secrets.token_hex(25)

        # --- Append the peer to the server config ---
        peer_block = (
            f"# {peer_id} start\n"
            f"[Peer]\n"
            f"PublicKey = {client_pub}\n"
            f"PresharedKey = {psk}\n"
            f"AllowedIPs = {client_v4}/32,{client_v6}/128\n"
            f"# {peer_id} end\n"
        )
        with open(WG_CONF, "a") as f:
            if not conf_text.endswith("\n"):
                f.write("\n")
            f.write(peer_block)

        # --- Add the peer to the live interface (PSK via temp file) ---
        # Note: temp file lives in /etc/wireguard, not /tmp — AppArmor
        # blocks `wg` from reading /tmp on recent Ubuntu releases.
        psk_file = None
        try:
            fd, psk_file = tempfile.mkstemp(dir="/etc/wireguard")
            with os.fdopen(fd, "w") as f:
                f.write(psk + "\n")
            run([
                "wg", "set", WG_INTERFACE,
                "peer", client_pub,
                "preshared-key", psk_file,
                "allowed-ips", f"{client_v4}/32,{client_v6}/128",
            ])
        finally:
            if psk_file and os.path.exists(psk_file):
                os.remove(psk_file)

        # --- Build the client config (wireguard-manager format) ---
        client_conf = (
            f"[Interface]\n"
            f"Address = {client_v4}/8,{client_v6}/8\n"
            f"DNS = {settings['dns']}\n"
            f"ListenPort = 27147\n"
            f"MTU = {settings['mtu']}\n"
            f"PrivateKey = {client_priv}\n"
            f"[Peer]\n"
            f"AllowedIPs = {settings['allowed_ips']}\n"
            f"Endpoint = {settings['endpoint']}\n"
            f"PersistentKeepalive = {settings['keepalive']}\n"
            f"PresharedKey = {psk}\n"
            f"PublicKey = {settings['server_pubkey']}\n"
        )

        # --- Keep a copy in clients/ ---
        client_path = os.path.join(CLIENTS_DIR, f"{peer_id}-{WG_INTERFACE}.conf")
        with open(client_path, "w") as f:
            f.write(client_conf)
        os.chmod(client_path, 0o600)

    return Response(client_conf, mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
```

## 📡 API Reference

| Method | Endpoint | Query Params | Response |
|--------|----------|--------------|----------|
| `GET` | `/wg-config` | `token` (required) | `200` — client config, `text/plain` |
| `GET` | `/wg-config` | missing/wrong token | `403 Forbidden` |

**Example response:**

```ini
[Interface]
Address = 12.0.0.3/8,fd00:00:00::3/8
DNS = 1.1.1.1,1.0.0.1,2606:4700:4700::1111,2606:4700:4700::1001
ListenPort = 27147
MTU = 1280
PrivateKey = <unique per request>
[Peer]
AllowedIPs = 0.0.0.0/0,::/0
Endpoint = <server-ip>:51820
PersistentKeepalive = 25
PresharedKey = <unique per request>
PublicKey = <server public key>
```

## 📲 Distributing Configs to Users

Each user/device must get its **own** config. Generate one per person on the server:

```bash
curl -s "http://127.0.0.1:5002/wg-config?token=$(sudo cat /root/wg-api-token.txt)" \
  | sudo tee /root/username-wg0.conf > /dev/null
```

Then deliver it via:

- **QR code (in person, most secure):** `sudo qrencode -t ansiutf8 < /root/username-wg0.conf` → scan with the WireGuard app
- **Secure message:** send the config text over a private channel; the user pastes it into WireGuard → *Create from scratch*
- ⚠️ Never share the API token itself — only distribute generated configs

**Revoking a user:** delete their `# <id> start ... end` block from `wg0.conf`, then `sudo systemctl restart wg-quick@wg0`.

## 🔧 Troubleshooting Notes

Real issues hit (and solved) during development:

| Symptom | Cause | Fix |
|---------|-------|-----|
| `wg set` fails: `fopen: Permission denied` | AppArmor blocks `wg` from reading PSK files in `/tmp` | Create the temp PSK file inside `/etc/wireguard` (`tempfile.mkstemp(dir=...)`) |
| `CalledProcessError` with no detail | `subprocess.run(check=True)` hides stderr | Custom `run()` wrapper that raises with the actual stderr text |
| `IndentationError` / `TabError` after edits | Mixed tabs and spaces | `sed -i 's/\t/    /g' wg_api.py` — always indent with spaces |
| Service `enabled` but port closed | Script crashing on startup | `journalctl -u wg-api.service -n 30` shows the Python traceback |
| Android: "file must be .zip .conf" | File saved with a hidden `.txt` extension | Serve the file with a proper `.conf` name, or paste the config manually |

## 🔐 Security Considerations

- The token is a single shared secret — rotate it if it ever leaks (`openssl rand -hex 16`, update the script, restart the service)
- The API serves **plain HTTP**; for production, put it behind a reverse proxy (Caddy/nginx) with TLS, or restrict port 5002 to trusted IPs via firewall
- The script runs as root because it must edit `/etc/wireguard` and call `wg set` — keep `wg_api.py` at mode `700`
- Generated configs contain private keys: distribute over secure channels and delete server-side copies you no longer need

## 📄 License

MIT License

```
MIT License

Copyright (c) 2026 Muaz Bhutta

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

*Built as part of a self-hosted DevOps lab — [muazbhutta.online](https://muazbhutta.online)*
