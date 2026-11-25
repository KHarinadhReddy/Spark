# Deploy Spark on Oracle Cloud Always Free

This is the production path used by the Docker stack: **one ARM VM, Docker
Compose, Caddy for HTTPS, SQLite on a named volume**. It fits comfortably in
Oracle's Always Free allowance.

> Spark is a single-user assistant. Do not scale the API to multiple replicas:
> SQLite and the approval-state checks assume one writer.

---

## 1. Create the VM

1. Sign in to [Oracle Cloud](https://cloud.oracle.com/) and pick your home region.
2. **Compute → Instances → Create instance**
   - **Image:** Canonical Ubuntu 24.04 (aarch64)
   - **Shape:** `VM.Standard.A1.Flex` — 2–4 OCPUs, 12–24 GB RAM (Always Free)
   - **Boot volume:** 50–100 GB
   - Add your SSH public key.
3. If Ampere capacity is unavailable, retry later or use `VM.Standard.E2.1.Micro`
   (AMD, 1 GB). Add 2 GB of swap on the micro shape (step 4).
4. Note the public IPv4 address.

### Open the firewall

In **Networking → VCN → Security Lists → Default Security List**, add ingress:

| Source | Protocol | Port |
|---|---|---|
| `0.0.0.0/0` | TCP | 80 |
| `0.0.0.0/0` | TCP | 443 |
| your IP | TCP | 22 |

Then on the VM itself (Oracle's Ubuntu images keep their own iptables rules):

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

If the image uses `ufw` instead:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

---

## 2. Point a domain at it

Create an **A record** for e.g. `spark.example.com` → VM public IP. Wait for it:

```bash
dig +short spark.example.com
```

No domain? `sslip.io` works without registration: use
`<public-ip>.sslip.io` as `SPARK_DOMAIN`, and Caddy will still get a real
Let's Encrypt certificate. A free DuckDNS subdomain also works.

---

## 3. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
docker run --rm hello-world
```

Optional swap on a 1 GB micro instance:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 4. Get Spark running

```bash
sudo mkdir -p /opt/spark
sudo chown "$USER":"$USER" /opt/spark
git clone https://github.com/KHarinadhReddy/Spark.git /opt/spark
cd /opt/spark

cp .env.example .env
chmod 600 .env
nano .env
```

Minimum values to set:

```env
SPARK_DOMAIN=spark.example.com
SPARK_PUBLIC_BASE_URL=https://spark.example.com
SPARK_BACKEND_URL=https://spark.example.com
SPARK_OWNER_TOKEN=<openssl rand -hex 32>
GOOGLE_REDIRECT_URI=https://spark.example.com/api/auth/google/callback
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GEMINI_API_KEY=...
GROQ_API_KEY=...
SPARK_EDGE_TTS=1
```

Create the backup directory (the container runs as UID 1000, matching the
default `ubuntu` user):

```bash
mkdir -p backups
docker compose up -d --build
docker compose ps
docker compose logs -f caddy api worker
```

When Caddy reports a certificate for your domain, open
`https://spark.example.com`.

> **Never expose port 8000 directly.** Only Caddy publishes 80/443.

---

## 5. Google OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) → create/select a project.
2. **APIs & Services → Library** → enable:
   - Gmail API
   - Google Calendar API
   - Google Drive API
3. **OAuth consent screen**
   - **Internal** if this is a Google Workspace account — no verification,
     long-lived refresh tokens. This is the recommended path.
   - **External** for a personal Gmail account. While the app is in *Testing*,
     add yourself under **Test users**. Google expires testing-mode refresh
     tokens after **7 days**, so Spark will need a weekly reconnect until the
     app is published/verified.
4. **Credentials → Create credentials → OAuth client ID → Web application**
   - Authorized redirect URI, exactly:
     `https://spark.example.com/api/auth/google/callback`
5. Put the client ID/secret into `.env` and restart:

```bash
docker compose up -d
```

6. In Spark: **Settings → Connections → Connect Google**, grant read/compose
   scopes, then wait for the first sync.

Scopes requested: Calendar events, Gmail read-only, Gmail compose, Drive
read-only. Spark cannot send email or modify Drive files.

### Free AI and voice keys

- Gemini API key: <https://aistudio.google.com/apikey>
- Groq API key: <https://console.groq.com/keys>
- Edge TTS is keyless — just keep `SPARK_EDGE_TTS=1`.

If Gemini is rate-limited, Spark falls back to Groq, then to the deterministic
local planner. Voice falls back to Groq Whisper / the browser voice.

---

## 6. First-run checklist

1. Open the site, go to **Settings → Access**, paste `SPARK_OWNER_TOKEN`, save.
2. **Settings → Connections → Connect Google**.
3. **Settings → Voice → Test voice** (English and Hindi).
4. **Inbox** shows real Gmail; **Deadlines** fills from synced messages.
5. **Settings → WhatsApp companion → Pair a device**, then paste the token into
   the Android app.
6. Load the Chrome extension, set the same backend URL and owner token.
7. Approve one small calendar write end-to-end, then undo it from Activity.

---

## 7. Backups

The `backup` service uses SQLite's online backup API and writes a zip with the
database and Google token:

```bash
cd /opt/spark
docker compose --profile tools run --rm backup
ls -lh backups/
```

Schedule it daily (03:15) and keep 14 days:

```bash
(crontab -l 2>/dev/null; \
 echo '15 3 * * * cd /opt/spark && docker compose --profile tools run --rm backup >> backups/backup.log 2>&1') \
 | crontab -
```

Restore (stop the stack first):

```bash
cd /opt/spark
docker compose down
docker run --rm -v spark_spark-data:/data -v "$PWD/backups:/backup" \
  python:3.13-slim \
  python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall('/data')" \
  /backup/spark-backup-YYYYMMDD-HHMMSS.zip
docker run --rm -v spark_spark-data:/data alpine chown -R 1000:1000 /data
docker compose up -d
```

Backups contain the Google OAuth token and every synced message — treat them
like a password. Copy them off the VM (`scp`) if the data matters.

---

## 8. Updating

```bash
cd /opt/spark
git pull
docker compose up -d --build
docker compose ps
```

The SQLite schema is created with `CREATE TABLE IF NOT EXISTS`, so additive
changes apply on startup. Take a backup before pulling a large update.

---

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| Caddy cannot get a certificate | DNS `dig`, ports 80/443 in **both** the VCN security list and VM iptables/ufw, `docker compose logs caddy` |
| `502 Bad Gateway` | `docker compose logs api`; `docker compose ps` health |
| `401 Spark is locked` | The browser/extension token does not match `SPARK_OWNER_TOKEN` |
| Google `redirect_uri_mismatch` | The URI in Google Console must exactly equal `GOOGLE_REDIRECT_URI` |
| Google `Access blocked` | Add your account as a test user, or publish the OAuth app |
| Google disconnects weekly | External app is still in Testing mode; publish it or use Workspace Internal |
| Companion `401` | Token was revoked or belongs to another deployment; pair again |
| Companion shows `Pair this device first` | The token is pasted with whitespace or the backend URL is wrong |
| `database is locked` | Only one `worker` container; do not scale replicas |
| Voice button does nothing | Browser mic permission, HTTPS required for mic, owner token accepted |
| Reminders not arriving | The worker container is running; in-app reminders appear in Notifications |
| Extension cannot reach Spark | Backend URL includes `https://`, token saved, and the site is reachable |

Useful commands:

```bash
docker compose logs --tail=200 api
docker compose logs --tail=200 worker
docker compose exec api python -c "from app.config import Settings; s=Settings.load(); print(s.mode, s.llm_provider, s.voice_provider)"
```

---

## 10. Security notes

- Set `SPARK_OWNER_TOKEN`. Without it, anyone with the URL can read the inbox.
- Keep `.env` at mode `600`; it holds Google, AI and owner secrets.
- Backups contain personal data; encrypt or delete old copies.
- Spark stores the Google refresh token in `data/google_token.json` inside the
  volume. Disk encryption is the VM's responsibility.
- Revoke a lost phone in **Settings → Paired devices**, and revoke Spark's
  Google access at <https://myaccount.google.com/permissions>.
- Enable Ubuntu unattended upgrades and keep Docker updated.

---

## Always Free reality check

- `VM.Standard.A1.Flex` capacity is often temporarily unavailable in popular
  regions. Retry, try another availability domain, or start on the micro shape.
- Always Free includes 10 TB/month outbound transfer — far more than a personal
  assistant needs.
- The whole stack (API + worker + Caddy) typically uses ~250–450 MB RAM.
