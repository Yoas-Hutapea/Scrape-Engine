# Captcha verification on Ubuntu Server

Shopee, Blibli and Alibaba sometimes answer the server with a captcha / verify page
(slider, Cloudflare Turnstile). The engine does not solve these. Instead a person
solves it once in a real browser window on the server, and the engine keeps using
that browser profile afterwards:

```
IDISys "Selesaikan captcha"  ->  POST /verify/sessions  ->  headed Camoufox on Xvfb :99
                                                             (profile output/profiles/<marketplace>)
person opens noVNC (VERIFY_VIEWER_URL), solves the captcha
engine sees the page is clear  ->  status "solved", cookies saved in the profile
later scrapes of that marketplace reuse the same profile (same cookies, fingerprint, IP)
```

Cookies such as `cf_clearance` are tied to the browser fingerprint and the server IP,
so the verification has to happen on the server itself, not on a desktop PC.

## Install

Prerequisite: the engine is installed as described in the main README (`.venv`,
`pip install -e .`, `python -m camoufox fetch`).

```bash
sudo SCRAPE_USER=scrape SCRAPE_DIR=/opt/Scrape-Engine \
     ENGINE_HOST=0.0.0.0 \
     ./deploy/ubuntu/setup-verify-display.sh
```

This installs Xvfb, openbox, x11vnc, noVNC and five systemd units:

| Unit | What |
|---|---|
| `scrape-xvfb` | virtual display `:99` |
| `scrape-openbox` | window manager on `:99` |
| `scrape-x11vnc` | VNC on `localhost:5900`, password in `/etc/scrape-engine/vncpasswd` |
| `scrape-novnc` | noVNC web viewer on `NOVNC_LISTEN` (default `127.0.0.1:6080`) |
| `scrape-engine` | the API with `DISPLAY=:99`, env from `/etc/scrape-engine/engine.env` |

`ENGINE_HOST=0.0.0.0` only if IDISys runs on another machine; then restrict port 8001
to the IDISys server with the firewall (`ufw allow from <idisys-ip> to any port 8001`).

## Expose noVNC safely

Anyone who reaches noVNC controls a browser that is logged in to the marketplaces.
Keep it on `127.0.0.1` and publish it through a reverse proxy with authentication,
reachable only from the office network. Example nginx:

```nginx
location /novnc/ {
    auth_basic "Scrape Engine";
    auth_basic_user_file /etc/nginx/scrape-novnc.htpasswd;   # htpasswd -c ...
    allow 10.0.0.0/8;       # office network
    deny all;

    proxy_pass http://127.0.0.1:6080/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 1h;
}
```

Then in `/etc/scrape-engine/engine.env`:

```
VERIFY_VIEWER_URL=https://scrape.internal.example/novnc/vnc.html?autoconnect=1&resize=scale&path=novnc/websockify
```

and `sudo systemctl restart scrape-engine`. IDISys opens this URL when someone clicks
"Selesaikan captcha". The VNC password is still asked by noVNC.

For a one-off without nginx: `ssh -L 6080:127.0.0.1:6080 user@server` and open
`http://localhost:6080/vnc.html`.

## Check

```bash
curl -s http://127.0.0.1:8001/verify/status | python3 -m json.tool
# display: true, viewer_url: ..., marketplaces.<name>.verified_at
curl -s -X POST http://127.0.0.1:8001/verify/sessions \
     -H 'Content-Type: application/json' -d '{"marketplace":"blibli"}'
```

The second call opens Blibli on `:99`; watch it in noVNC. The session turns `solved`
once the page shows no captcha for two checks in a row, or `expired` after
`VERIFY_TIMEOUT_SEC` (default 600).

## Notes

- One verification window per marketplace. While it is open, scrapes of that
  marketplace are skipped with `code=captcha_required` ("verifikasi captcha sedang
  berjalan"); other marketplaces keep working.
- Profiles live in `output/profiles/<marketplace>` (Shopee: `output/shopee-profile`).
  They contain session cookies: they are git-ignored, back them up like secrets.
- Solved sessions last as long as the marketplace keeps the cookies (hours to days).
  Heavy scraping makes the captcha come back sooner.
