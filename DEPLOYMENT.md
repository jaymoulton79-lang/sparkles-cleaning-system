# Production deployment

Sparkles runs as a single Docker container. Local development uses SQLite, but Railway production should use PostgreSQL via `DATABASE_URL` so bookings, payments and cleaner records survive redeploys. Put it behind a TLS-terminating reverse proxy or a cloud HTTPS load balancer.

## 1. Configure secrets

Copy `.env.example` to `.env` and replace every placeholder. At minimum set:

- `PUBLIC_URL` to the final HTTPS URL.
- `DATABASE_URL` to the Railway PostgreSQL connection string in production.
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

Subscribe to `checkout.session.completed`, `invoice.paid` and `invoice.payment_succeeded`, then set the resulting signing secret. The invoice events are required for final balance payments to move bookings from `Balance Due` to `Paid in Full`.

## 4. Cloud deployment

Deploy the image to any container host that supports PostgreSQL or a persistent volume, including AWS ECS, Google Cloud Run, Azure Container Apps, Fly.io, Render, Railway or a Linux VM. Configure:

- Container port: `8000`
- Liveness path: `/healthz`
- Readiness path: `/readyz`
- Minimum instances: `1`
- Maximum instances: `1`

The embedded automation worker should still run with a single application replica. Before scaling horizontally, run the automation worker as a separate service.

### Railway

Recommended Railway setup:

- Add Railway PostgreSQL.
- Copy the Postgres `DATABASE_URL` into the app service variables.
- Keep replicas/instances at `1`.
- Use `/readyz` as the health check path.

If you choose the SQLite fallback instead of PostgreSQL, Railway does not support Dockerfile `VOLUME` instructions. Create a Railway Volume in the Railway dashboard and mount it to `/app/data`, then set `SPARKLES_DB_PATH=/app/data/sparkles.db`. PostgreSQL is safer for production.

Set these Railway service values:

- Start command: use the Dockerfile default, `python server.py`.
- Public port: `8000`.
- Health check path: `/readyz`.
- Replicas/instances: `1`.

### SQLite to PostgreSQL migration

1. Before changing production variables, export the existing SQLite database from the current deployment or download `/app/data/sparkles.db` if it is on a Railway Volume.
2. Add Railway PostgreSQL to the project.
3. Set the app service `DATABASE_URL` to the Railway PostgreSQL connection string.
4. From a trusted machine with the SQLite file available, run:

```bash
pip install -r requirements.txt
DATABASE_URL="postgresql://..." python migrate_sqlite_to_postgres.py --source ./sparkles.db
```

5. Redeploy the app.
6. Log into `/admin/diagnostics` and confirm the tables have non-zero row counts.
7. Create a new test booking, redeploy, and confirm the booking remains visible.

## 5. Backups and restore

For PostgreSQL, use Railway's PostgreSQL backups/exports and test restoration regularly. If using SQLite fallback, back up `/app/data/sparkles.db` and `/app/data/uploads` every day.

## 6. Logs and operations

Application and HTTP access logs are emitted as JSON on stdout for ingestion by the cloud logging service. Alert on:

- `/readyz` failures
- repeated HTTP 500 responses
- automation jobs in `Failed`
- Stripe webhook signature errors
- SMTP delivery failures

The workflow monitor is available at `/admin/automations`.
