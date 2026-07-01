# Production deployment

Sparkles runs as a single Docker container with a persistent SQLite data volume. Put it behind a TLS-terminating reverse proxy or a cloud HTTPS load balancer.

## 1. Configure secrets

Copy `.env.example` to `.env` and replace every placeholder. At minimum set:

- `PUBLIC_URL` to the final HTTPS URL.
- `ADMIN_SETUP_TOKEN` to a long random value (32+ bytes).
- Stripe test or live secret and webhook signing secrets.
- SMTP host, port, username, password and sender.
- `REVIEW_URL` to the company review page.

Environment variables override values saved by the setup wizard. Prefer the cloud provider's secret manager for production credentials. Never commit `.env`.

## 2. Start with Docker Compose

```bash
docker compose up -d --build
docker compose ps
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

Open `/admin/setup`, enter `ADMIN_SETUP_TOKEN`, and complete the wizard.

## 3. Configure HTTPS and Stripe

Route the public hostname to port 8000 through Caddy, Nginx, Traefik or the cloud load balancer. Only expose HTTPS publicly. Create a Stripe webhook destination at:

```text
https://YOUR_DOMAIN/api/stripe/webhook
```

Subscribe to `checkout.session.completed` and `invoice.paid`, then set the resulting signing secret.

## 4. Cloud deployment

Deploy the image to any container host that supports a persistent volume, including AWS ECS, Google Cloud Run with a mounted volume, Azure Container Apps, Fly.io, Render or a Linux VM. Configure:

- Container port: `8000`
- Liveness path: `/healthz`
- Readiness path: `/readyz`
- Persistent mount: `/app/data`
- Minimum instances: `1`
- Maximum instances: `1`

SQLite and the embedded automation worker require a single application replica. Before scaling horizontally, move bookings, jobs and configuration to PostgreSQL and run the automation worker as a separate service.

### Railway

Railway does not support Dockerfile `VOLUME` instructions. The Dockerfile is intentionally free of `VOLUME`; create a Railway Volume in the Railway dashboard and mount it to:

```text
/app/data
```

This keeps the SQLite database and uploaded photos persistent while staying compatible with Railway's build system.

Set these Railway service values:

- Start command: use the Dockerfile default, `python server.py`.
- Public port: `8000`.
- Health check path: `/readyz`.
- Volume mount path: `/app/data`.
- Replicas/instances: `1`.

## 5. Backups and restore

Back up `/app/data/sparkles.db` and `/app/data/uploads` every day. Test restoration regularly. For a consistent SQLite backup, use the SQLite online backup API or briefly stop the container before copying the database.

## 6. Logs and operations

Application and HTTP access logs are emitted as JSON on stdout for ingestion by the cloud logging service. Alert on:

- `/readyz` failures
- repeated HTTP 500 responses
- automation jobs in `Failed`
- Stripe webhook signature errors
- SMTP delivery failures

The workflow monitor is available at `/admin/automations`.
