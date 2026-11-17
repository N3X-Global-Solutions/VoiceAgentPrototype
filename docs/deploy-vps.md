# Deploy VoicePilot to the VPS

**URL:** https://voicepilot.n3xglobalsolutions.com
**Server:** the Hostinger VPS that already runs GoldCRM behind **Nginx**
**DNS:** Cloudflare (zone `n3xglobalsolutions.com`)

Frontend and backend run in **one Docker container** (`voice-agent-studio-app-1`), listening only on `127.0.0.1:7860`. The server's existing Nginx gives it the public domain, and certbot gives it HTTPS. GoldCRM and its databases are not touched.

```
Browser ──https──► Cloudflare DNS ──► VPS: Nginx :443 ──► 127.0.0.1:7860  (VoicePilot container: UI + API)
Browser ◄══ voice audio (UDP, WebRTC) ══► VPS directly
Twilio / Exotel ──► https://voicepilot.n3xglobalsolutions.com (webhooks + WebSockets)
```

HTTPS is required: browsers only allow the microphone (for test calls) on HTTPS pages.

**Order matters:** the DNS record (step 1) must exist **before** certbot (step 7). Let's Encrypt checks that the domain points at this server before it issues the certificate.

---

## 1. Cloudflare: add the DNS record (do this first)

Cloudflare dashboard → **n3xglobalsolutions.com** → **DNS** → **Records** → **Add record**:

| Field | Value |
|---|---|
| Type | `A` |
| Name | `voicepilot` |
| IPv4 address | your VPS IP (`hostname -I` on the server, or hPanel → VPS) |
| Proxy status | **DNS only** (grey cloud), turn the orange cloud **off** |
| TTL | Auto |

Save it, then check from the server (Cloudflare usually updates within a minute):

```bash
dig +short voicepilot.n3xglobalsolutions.com     # must print the VPS IP
```

Why **DNS only**:
- certbot can issue and renew the certificate without extra Cloudflare settings.
- Phone-call WebSockets connect straight to the server.
- Browser call audio goes to the server's IP directly anyway (WebRTC), so the proxy wouldn't hide it.

If you want the orange cloud later, see [Optional: Cloudflare proxy](#optional-cloudflare-proxy-orange-cloud).

## 2. Firewall: allow call audio (once)

Ports 22, 80 and 443 are already open. Only **add** UDP for browser-call audio. Don't run `ufw enable` or `ufw reset` on this server:

```bash
ufw allow 1024:65535/udp
```

This only exposes programs that listen on UDP. GoldCRM and Postgres use TCP, so they're unaffected. If the Hostinger **hPanel firewall** is enabled for this VPS, add the same UDP range there.

## 3. Copy the app to the server

On your Mac, from the project folder:

```bash
rsync -av --exclude node_modules --exclude .venv --exclude backend/data --exclude .git \
  --exclude .env --exclude frontend/dist ./ root@YOUR_VPS_IP:/opt/voice-agent-studio/
```

(Or `git clone` the repo into `/opt/voice-agent-studio`, but only after committing and pushing every change. The server only sees what's on GitHub.)

## 4. Configure

On the server:

```bash
cd /opt/voice-agent-studio
cp .env.example .env
echo "SESSION_SECRET=$(openssl rand -hex 32)"     # copy this line into .env
nano .env
chmod 600 .env
```

`.env.example` already has the domain filled in. Check these lines:

```ini
SARVAM_API_KEY=sk_...                                        # your real key
DOMAIN=voicepilot.n3xglobalsolutions.com
PUBLIC_BASE_URL=https://voicepilot.n3xglobalsolutions.com
ADMIN_EMAIL=admin@n3xglobalsolutions.com
ADMIN_PASSWORD=...                                           # admin sign-in password
SESSION_SECRET=...                                           # from the echo above
```

Add Twilio/Exotel values if you use phone calls.

## 5. Build and start the container

```bash
docker compose up -d --build       # first build takes a few minutes
docker compose ps                  # voice-agent-studio-app-1 → "healthy" after ~30 s
curl -s http://127.0.0.1:7860/api/healthz      # {"ok":true}
```

This starts **only** the VoicePilot container. The bundled Caddy proxy is optional and stays off, because Nginx already owns ports 80/443.

## 6. Nginx: add the site

```bash
cp deploy/nginx-site.conf /etc/nginx/sites-available/voicepilot
ln -s /etc/nginx/sites-available/voicepilot /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

`nginx -t` checks the whole config first. If it reports an error, the reload doesn't happen and GoldCRM keeps running. Now `http://voicepilot.n3xglobalsolutions.com` reaches the app (not HTTPS yet).

## 7. HTTPS certificate

The DNS record from step 1 must already point at this server:

```bash
which certbot || apt install -y certbot python3-certbot-nginx
certbot --nginx -d voicepilot.n3xglobalsolutions.com
```

When asked, choose to **redirect** HTTP to HTTPS. certbot renews the certificate automatically. Test renewal with `certbot renew --dry-run`.

## 8. Open it

Go to **https://voicepilot.n3xglobalsolutions.com** and sign in with the admin email and password.

**Phone providers:** in the app, open **Settings → Telephony webhooks** and copy the URLs:
- **Twilio:** your number → Voice webhook, HTTP POST.
- **Exotel:** the Voicebot applet.

---

## Day-to-day

Always run these from `/opt/voice-agent-studio`, so they only affect VoicePilot.

```bash
# Update: rsync again from your Mac (or git pull), then rebuild
docker compose up -d --build

# Logs
docker compose logs -f app

# Apply .env changes
docker compose up -d

# Back up the database
docker compose cp app:/app/data/app.db ./backup-$(date +%F).db
```

**Move your local data to the server** (optional; copy `backend/data/app.db` up first):

```bash
docker compose cp ./app.db app:/app/data/app.db
docker compose exec -u root app chown app:app /app/data/app.db
docker compose restart app
```

Don't run `docker system prune -a` or `docker volume prune` on this server. They can delete GoldCRM's images and data.

## Troubleshooting

| Symptom | Fix |
|---|---|
| certbot: "DNS problem" / "unauthorized" | The Cloudflare record is missing, still proxied (orange), or the IP is wrong. `dig +short voicepilot.n3xglobalsolutions.com` must print the VPS IP. |
| `502 Bad Gateway` | The container isn't running or healthy: `docker compose ps`, `docker compose logs app`. |
| Browser call says "Connecting…" forever, or no audio | UDP is blocked: re-check step 2, including the hPanel firewall. |
| Mic permission never appears | You're on `http://`. Use `https://`. |
| "Too many failed sign-in attempts" | Wait 15 minutes, or `docker compose restart app`. |
| Signed out after changing `.env` | Expected: changing `ADMIN_PASSWORD` or `SESSION_SECRET` signs everyone out. |
| Phone calls don't reach the agent | `PUBLIC_BASE_URL` must be `https://voicepilot.n3xglobalsolutions.com`, and the provider must use the URLs from Settings. |

## Optional: Cloudflare proxy (orange cloud)

Only do this after the site works with DNS only. It adds Cloudflare's DDoS protection and caching. It needs three things, or logins and certificates break:

1. **SSL mode Full (strict), for this hostname only.** Cloudflare's SSL mode is zone-wide by default, and changing it can break other `n3xglobalsolutions.com` sites. Instead add **Rules → Configuration Rules** → hostname equals `voicepilot.n3xglobalsolutions.com` → SSL: **Full (strict)**.
2. **Real visitor IPs in Nginx.** Without this, every visitor appears as a Cloudflare IP. The login lockout (8 failed attempts) would then lock out everyone together. Add to the `server { }` block in `/etc/nginx/sites-available/voicepilot`, using the current ranges from https://www.cloudflare.com/ips/:

   ```nginx
   set_real_ip_from 173.245.48.0/20;   # …one line per Cloudflare range (IPv4 and IPv6)
   real_ip_header CF-Connecting-IP;
   ```

   Then `nginx -t && systemctl reload nginx`.
3. **Certificate renewal:** run `certbot renew --dry-run`. If it fails behind the proxy, switch the record back to DNS only while renewing, or use certbot's Cloudflare DNS plugin.

Then switch the record's proxy status to **Proxied**.

## Appendix: server without Nginx

On a fresh server with nothing on ports 80/443, skip steps 6–7 and start the bundled Caddy proxy instead. It gets the certificate automatically for `DOMAIN`:

```bash
docker compose --profile caddy up -d --build
```

`deploy/Caddyfile` configures it.
