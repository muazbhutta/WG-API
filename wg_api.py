 #!/usr/bin/env python3
"""WireGuard config generator API — values wg0.conf se pick hoti hain."""

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
CLIENT_MTU_INDEX = 5  # header line mein MTU ka position
API_TOKEN = "955f882ab363efc88f3c1400ea20e22d"

app = Flask(__name__)
CORS(app)
lock = threading.Lock()  # do requests ek saath aayen to file corrupt na ho

def run(cmd, input_text=None):
    """Shell command chalao aur stdout wapis do."""
    result = subprocess.run(
        cmd, input=input_text, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()

def parse_header(conf_text):
    """wg0.conf ki pehli comment line se saari settings nikalo.
    Format: # <v4subnet> <v6subnet> <endpoint> <serverpubkey> <dns> <mtu> <keepalive> <allowedips>
    """
    first_line = conf_text.splitlines()[0]
    parts = first_line.lstrip("#").split()
    return {
        "v4_subnet": parts[0],       # 12.0.0.0/8
        "v6_subnet": parts[1],       # fd00:00:00::0/8
        "endpoint": parts[2],        # 152.42.241.74:51820
        "server_pubkey": parts[3],
        "dns": parts[4],
        "mtu": parts[5],             # 1280 (client MTU)
        "keepalive": parts[6],
        "allowed_ips": parts[7],     # 0.0.0.0/0,::/0
    }


def next_free_host(conf_text, v4_subnet):
    """Existing peers ke AllowedIPs dekh ke agla free host number do."""
    used = set()
    for line in conf_text.splitlines():
        line = line.strip()
        if line.startswith("AllowedIPs") and "/32" in line:
            ip_part = line.split("=")[1].split(",")[0].strip()  # 12.0.0.2/32
            ip = ipaddress.ip_address(ip_part.split("/")[0])
            used.add(int(ip) & 0xFF)  # aakhri octet
    host = 2
    while host in used:
        host += 1
    if host > 254:
        raise RuntimeError("Subnet full: koi free IP nahi bacha")
    return host


@app.route("/wg-config", methods=["GET"])
def wg_config():
    if request.args.get("token") != API_TOKEN:
        abort(403)
    with lock:
        with open(WG_CONF, "r") as f:
            conf_text = f.read()

        settings = parse_header(conf_text)

        # --- Naya IP ---
        host = next_free_host(conf_text, settings["v4_subnet"])
        base_v4 = settings["v4_subnet"].split("/")[0].rsplit(".", 1)[0]  # 12.0.0
        client_v4 = f"{base_v4}.{host}"
        v6_prefix = settings["v6_subnet"].split("/")[0].rsplit("::", 1)[0]  # fd00:00:00
        client_v6 = f"{v6_prefix}::{host}"

        # --- Naye keys (har request par fresh) ---
        client_priv = run(["wg", "genkey"])
        client_pub = run(["wg", "pubkey"], input_text=client_priv)
        psk = run(["wg", "genpsk"])

        # --- Peer ID (wireguard-manager jaisa random hex) ---
        peer_id = secrets.token_hex(25)

        # --- Server config mein peer append karo ---
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

        # --- Live interface mein add karo (PSK temp file ke zariye) ---
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

        # --- Client config (wireguard-manager format) ---
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

        # --- clients/ folder mein bhi save karo ---
        client_path = os.path.join(CLIENTS_DIR, f"{peer_id}-{WG_INTERFACE}.conf")
        with open(client_path, "w") as f:
            f.write(client_conf)
        os.chmod(client_path, 0o600)

    return Response(client_conf, mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)

