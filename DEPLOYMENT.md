# ReportGPS — Server Deployment Guide

This guide walks through deploying ReportGPS on the college server using Docker.

---

## Prerequisites (One-Time Setup on the College Server)

- Docker and Docker Compose installed (confirm with IT)
- Ports **80** and **443** open/forwarded to the server (confirm with IT)
- SSH access to the server
- Domain A records set in Hostinger (see Step 1 below)

---

## Step 1 — Configure DNS in Hostinger

1. Log into [Hostinger hPanel](https://hpanel.hostinger.com)
2. Go to **Domains → reportgps.com → DNS / Nameservers**
3. Add these two A records:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `@` | `COLLEGE_SERVER_PUBLIC_IP` | 300 |
| A | `www` | `COLLEGE_SERVER_PUBLIC_IP` | 300 |

> DNS propagation takes 5–30 minutes. You can check with `nslookup reportgps.com`.

---

## Step 2 — Clone the Repository on the Server

SSH into the college server, then:

```bash
git clone https://github.com/06hardik/reportgps.git
cd reportgps
```

---

## Step 3 — Create the Environment File

The `.env` file is never committed to Git. Create it manually on the server:

```bash
cp services/extraction-pipeline/.env.example services/extraction-pipeline/.env
nano services/extraction-pipeline/.env
```

Fill in your actual API keys (Groq, Cerebras, Gemini).

---

## Step 4 — Update the Certbot Email

Open `docker-compose.yml` and replace the placeholder email:

```yaml
# Change this line in the certbot service:
--email your-email@example.com
```

---

## Step 5 — Get the SSL Certificate (First Time Only)

> **Important:** Do this BEFORE starting the main stack, otherwise Nginx will fail to start because the certificate files don't exist yet.

```bash
# Start Nginx on HTTP only first (temporary config)
# We need Nginx running for the ACME challenge to work
docker compose up -d nginx

# Run certbot to get the certificate
docker compose run --rm certbot

# Restart Nginx to load the new certificate
docker compose restart nginx
```

If successful, you'll see: `Congratulations! Your certificate and chain have been saved...`

---

## Step 6 — Start the Full Stack

```bash
docker compose up -d
```

This starts all 4 services in the background:
- `reportgps-pipeline` — Python FastAPI (internal)
- `reportgps-backend` — Node.js proxy (internal)
- `reportgps-frontend` — React via Nginx (internal)
- `reportgps-nginx` — Public reverse proxy on ports 80 + 443

---

## Step 7 — Verify Everything is Running

```bash
# Check all containers are up
docker compose ps

# Check logs for any errors
docker compose logs --tail=50

# Test the health endpoint
curl https://reportgps.com/api/upload -I
# Should return HTTP 405 (Method Not Allowed) — means the API is live
```

Open `https://reportgps.com` in your browser — the app should load.

---

## Useful Commands

```bash
# View live logs from all services
docker compose logs -f

# View logs from one service only
docker compose logs -f pipeline

# Restart a specific service (e.g., after updating .env)
docker compose restart pipeline

# Stop everything
docker compose down

# Rebuild and restart (after a code update)
git pull
docker compose up -d --build

# Check disk usage of Docker images
docker system df
```

---

## SSL Certificate Renewal (Automatic)

Let's Encrypt certificates expire after 90 days. To renew:

```bash
docker compose run --rm certbot renew
docker compose restart nginx
```

Set this as a monthly cron job on the server to automate it:

```bash
crontab -e
# Add this line:
0 3 1 * * cd /path/to/reportgps && docker compose run --rm certbot renew && docker compose restart nginx
```

---

## Architecture Overview

```
Internet → reportgps.com (port 443)
    ↓
[Nginx container]  — SSL termination
    ├── /api/*  →  [Backend container :5001]
    │                    ↓
    │            [Pipeline container :8004]
    │
    └── /*      →  [Frontend container :80]
                   (React static files)
```

All inter-service traffic is on a private Docker bridge network. Only Nginx is exposed to the internet.
