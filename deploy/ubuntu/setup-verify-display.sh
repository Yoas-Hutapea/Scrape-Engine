#!/usr/bin/env bash
# Virtual display + noVNC for captcha verification on Ubuntu Server.
#
#   Xvfb :99  ->  x11vnc (localhost:5900, password)  ->  noVNC/websockify (NOVNC_LISTEN)
#   Scrape Engine runs with DISPLAY=:99, so verification windows (and scrapes) show
#   up there and a person can solve the captcha from a browser.
#
# Usage (as root):
#   SCRAPE_USER=scrape SCRAPE_DIR=/opt/Scrape-Engine ./setup-verify-display.sh
# Optional:
#   DISPLAY_NUM=99  SCREEN=1366x900x24  NOVNC_LISTEN=127.0.0.1:6080
#   ENGINE_HOST=127.0.0.1 (use the LAN IP when IDISys runs on another server)  ENGINE_PORT=8001
set -euo pipefail

SCRAPE_USER="${SCRAPE_USER:?set SCRAPE_USER (Linux user that runs Scrape Engine)}"
SCRAPE_DIR="${SCRAPE_DIR:?set SCRAPE_DIR (Scrape-Engine checkout, contains .venv)}"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
SCREEN="${SCREEN:-1366x900x24}"
NOVNC_LISTEN="${NOVNC_LISTEN:-127.0.0.1:6080}"
ENGINE_HOST="${ENGINE_HOST:-127.0.0.1}"
ENGINE_PORT="${ENGINE_PORT:-8001}"
CONF_DIR=/etc/scrape-engine

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi
if [[ ! -x "$SCRAPE_DIR/.venv/bin/python" ]]; then
  echo "No virtualenv at $SCRAPE_DIR/.venv (see README: python3 -m venv .venv && pip install -e .)." >&2
  exit 1
fi

apt-get update
apt-get install -y xvfb x11vnc novnc websockify openbox fonts-liberation

install -d -m 0750 -o root -g "$SCRAPE_USER" "$CONF_DIR"
if [[ ! -f "$CONF_DIR/vncpasswd" ]]; then
  echo "Choose the VNC password (people opening noVNC must enter it):"
  x11vnc -storepasswd "$CONF_DIR/vncpasswd"
  chown root:"$SCRAPE_USER" "$CONF_DIR/vncpasswd"
  chmod 0640 "$CONF_DIR/vncpasswd"
fi

cat > /etc/systemd/system/scrape-xvfb.service <<UNIT
[Unit]
Description=Virtual display :$DISPLAY_NUM for Scrape Engine
After=network.target

[Service]
User=$SCRAPE_USER
ExecStart=/usr/bin/Xvfb :$DISPLAY_NUM -screen 0 $SCREEN -nolisten tcp
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

# A window manager keeps the verification window maximised and movable.
cat > /etc/systemd/system/scrape-openbox.service <<UNIT
[Unit]
Description=Window manager on :$DISPLAY_NUM
Requires=scrape-xvfb.service
After=scrape-xvfb.service

[Service]
User=$SCRAPE_USER
Environment=DISPLAY=:$DISPLAY_NUM
ExecStart=/usr/bin/openbox
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/scrape-x11vnc.service <<UNIT
[Unit]
Description=VNC server for display :$DISPLAY_NUM (localhost only)
Requires=scrape-xvfb.service
After=scrape-xvfb.service

[Service]
User=$SCRAPE_USER
ExecStart=/usr/bin/x11vnc -display :$DISPLAY_NUM -localhost -rfbport 5900 -rfbauth $CONF_DIR/vncpasswd -forever -shared -noxdamage -quiet
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/scrape-novnc.service <<UNIT
[Unit]
Description=noVNC web viewer for captcha verification
Requires=scrape-x11vnc.service
After=scrape-x11vnc.service

[Service]
User=$SCRAPE_USER
ExecStart=/usr/bin/websockify --web /usr/share/novnc $NOVNC_LISTEN localhost:5900
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/scrape-engine.service <<UNIT
[Unit]
Description=Scrape Engine API
Requires=scrape-xvfb.service
After=scrape-xvfb.service network-online.target

[Service]
User=$SCRAPE_USER
WorkingDirectory=$SCRAPE_DIR
Environment=DISPLAY=:$DISPLAY_NUM
EnvironmentFile=-$CONF_DIR/engine.env
ExecStart=$SCRAPE_DIR/.venv/bin/python -m scrape_engine.cli serve --host $ENGINE_HOST --port $ENGINE_PORT
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT

if [[ ! -f "$CONF_DIR/engine.env" ]]; then
  cat > "$CONF_DIR/engine.env" <<'ENV'
# URL that IDISys users open to solve the captcha (through your reverse proxy / tunnel).
# Example: https://scrape.internal.example/novnc/vnc.html?autoconnect=1&resize=scale
VERIFY_VIEWER_URL=
# Seconds a verification window stays open waiting for a person.
VERIFY_TIMEOUT_SEC=600
ENV
  chown root:"$SCRAPE_USER" "$CONF_DIR/engine.env"
  chmod 0640 "$CONF_DIR/engine.env"
fi

systemctl daemon-reload
systemctl enable --now scrape-xvfb scrape-openbox scrape-x11vnc scrape-novnc scrape-engine

echo
echo "Done. noVNC listens on $NOVNC_LISTEN (password from $CONF_DIR/vncpasswd)."
echo "Set VERIFY_VIEWER_URL in $CONF_DIR/engine.env, then: systemctl restart scrape-engine"
