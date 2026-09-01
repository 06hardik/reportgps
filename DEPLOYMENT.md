# ReportGPS — Production Deployment Guide
## (Cloudflare Tunnel Edition — No Port Forwarding Required)

This guide deploys ReportGPS on the college server and makes it publicly
accessible at **https://reportgps.com** using Cloudflare Tunnel.

No firewall rules, no port forwarding, and no SSL certificate management
is required. Cloudflare handles all of that for free.

---

## How It Works

```
User → https://reportgps.com
         ↓
   Cloudflare Edge (handles SSL, DDoS protection)
         ↓
   Cloudflare Tunnel (outbound connection from your server)
         ↓
   College Server (Docker containers, no open ports needed)
         ↓
   nginx → frontend / backend → pipeline
```

The college server never needs to open any inbound ports. The `cloudflared`
container makes an **outbound-only** connection to Cloudflare.

---

## Prerequisites

| Requirement | Status |
|---|---|
| Docker + Docker Compose installed on college server | Confirmed ✅ |
| Terminal (SSH) access to the college server | Confirmed ✅ |
| Domain `reportgps.com` purchased from Hostinger | Confirmed ✅ |
| Free Cloudflare account | Create at cloudflare.com |

---

## PART A — One-Time Cloudflare Setup (Do This on Your Laptop)

### Step A1 — Add Your Domain to Cloudflare

1. Go to [cloudflare.com](https://cloudflare.com) → Sign up for a **free account**
2. Click **Add a site** → enter `reportgps.com` → choose **Free plan**
3. Cloudflare will scan your existing DNS records (import them automatically)
4. Cloudflare gives you **two nameservers**, e.g.:
   - `alice.ns.cloudflare.com`
   - `bob.ns.cloudflare.com`

### Step A2 — Change Nameservers in Hostinger

1. Log into [Hostinger hPanel](https://hpanel.hostinger.com)
2. Go to **Domains → reportgps.com → DNS / Nameservers**
3. Select **Change Nameservers**
4. Replace the existing nameservers with the two Cloudflare ones from Step A1
5. Click Save. Propagation takes **5–30 minutes**.

> Once done, Cloudflare controls all DNS for reportgps.com. Your domain
> remains registered at Hostinger — you're only moving DNS management.

### Step A3 — Create the Cloudflare Tunnel

1. In the Cloudflare dashboard → click **Zero Trust** (left sidebar)
2. Go to **Networks → Tunnels → Create a tunnel**
3. Select **Cloudflared** → click **Next**
4. Name the tunnel: `reportgps` → click **Save tunnel**
5. On the next screen, Cloudflare shows you a **tunnel token** — a long string
   starting with `eyJ...`. **Copy this — you will need it in Part B.**
6. Click **Next** — you'll now configure the public hostname:

### Step A4 — Configure the Public Hostname in Cloudflare

Still in the tunnel setup (or go to the tunnel → **Public Hostnames** tab):

| Field | Value |
|---|---|
| Subdomain | *(leave blank for root domain)* |
| Domain | `reportgps.com` |
| Type | `HTTP` |
| URL | `nginx:80` |

Click **Save hostname**. Then add a second one:

| Field | Value |
|---|---|
| Subdomain | `www` |
| Domain | `reportgps.com` |
| Type | `HTTP` |
| URL | `nginx:80` |

> This tells Cloudflare: "Send traffic for reportgps.com to the container
> named `nginx` on port 80 inside my Docker network."

---

## PART B — Server Deployment (Do This on the College Server Terminal)

### Step B1 — Clone the Repository

```bash
git clone https://github.com/06hardik/reportgps.git
cd reportgps
```

### Step B2 — Create the Root Environment File (Tunnel Token)

```bash
cp .env.example .env
nano .env
```

Replace `paste_your_tunnel_token_here` with the token you copied in Step A3:

```
CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiNzE...your_actual_token...
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

### Step B3 — Create the Pipeline Environment File (API Keys)

```bash
cp services/extraction-pipeline/.env.example services/extraction-pipeline/.env
nano services/extraction-pipeline/.env
```

Fill in your Groq, Cerebras, and Gemini API keys. Save and exit.

### Step B4 — Start Everything

```bash
docker compose up -d --build
```

This command:
1. Builds all Docker images (Python deps, Node deps, React build)
2. Starts all 5 containers
3. The `cloudflared` container connects to Cloudflare automatically
4. Your site is live at **https://reportgps.com**

First build takes ~5–10 minutes (downloading base images + installing deps).
Subsequent starts take ~30 seconds.

### Step B5 — Verify Everything is Running

```bash
# Check all 5 containers show status "Up"
docker compose ps

# Watch logs in real time
docker compose logs -f

# Check the cloudflared tunnel status specifically
docker compose logs cloudflared
# Should see: "Connection registered" — this means the tunnel is active

# Test from the server itself
curl http://localhost   # won't work (no port exposed) — use the URL instead
```

Open **https://reportgps.com** in your browser — the site should load with
a valid SSL certificate (padlock icon).

---

## Updating the App After Code Changes

```bash
# On the college server:
git pull
docker compose up -d --build
```

Only containers whose source code changed will be rebuilt. Unchanged
containers restart instantly.

---

## Useful Commands

```bash
# View live logs from all containers
docker compose logs -f

# View logs from one container only
docker compose logs -f cloudflared
docker compose logs -f pipeline
docker compose logs -f backend

# Restart one container (e.g., after changing .env)
docker compose restart pipeline

# Stop everything
docker compose down

# Check disk usage
docker system df

# Free up old images after updates
docker image prune -f
```

---

## Troubleshooting

### Site not loading after `docker compose up`
```bash
docker compose logs cloudflared
```
Look for `Connection registered`. If you see an error, the tunnel token may
be wrong — double-check Step B2.

### Pipeline errors
```bash
docker compose logs pipeline
```
If you see API key errors, check `services/extraction-pipeline/.env`.

### Check if the tunnel is active from Cloudflare's side
Cloudflare Dashboard → Zero Trust → Networks → Tunnels →
the `reportgps` tunnel should show **HEALTHY** (green dot).

---

## Architecture Summary

```
┌─────────── College Server (Docker) ──────────────────────┐
│                                                           │
│  cloudflared ──outbound tunnel──► Cloudflare Edge        │
│       │                            (HTTPS for users)     │
│       ▼                                                   │
│  nginx:80 (internal HTTP only, not exposed)              │
│    ├── /api/*  →  backend:5001                           │
│    └── /*      →  frontend:80                            │
│                        │                                  │
│                   pipeline:8004                           │
└───────────────────────────────────────────────────────────┘

No inbound ports open. No SSL certs to manage.
Cloudflare provides: HTTPS, DDoS protection, CDN, free SSL.
```
