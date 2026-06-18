# Deployment

GraphCraft deploys as two long-running containers:

- **`collab`** — the Fastify + WebSocket hub (`@graphcraft/collab-service`) on port `4001`.
- **`frontend`** — the Vue app built to static assets and served by nginx on port
  `8080`, reverse-proxying `/api` and `/ws` to `collab`.

The **`mcp-service`** is a stdio process used by an agent/MCP client (e.g. Claude
Code), not a network service — it is not part of the compose stack. See
[README](README.md#connect-an-agent-mcp).

---

## 1. Prerequisites

- Docker Engine 24+ and the Docker Compose plugin (`docker compose`).
- A `.env` file at the repo root (copy from `.env.example`):

```bash
cp .env.example .env
```

Fill in only what you use. For a minimal demo you can leave every LLM key empty
(tier-1 curation + the keyless graph builder work without one). To enable RAG /
the LLM builder, set e.g. `DEEPSEEK_API_KEY=…`.

> **Secrets never go into the image.** They are injected at runtime from `.env`
> via Compose `env_file`. Do not bake keys into Dockerfiles.

---

## 2. Bring it up

```bash
docker compose up -d --build
```

- Frontend: http://localhost:8080
- Hub (direct): http://localhost:4001

Graph stores are persisted to a named volume (`graphcraft_graphs`) so they survive
restarts. To use a host directory instead, edit the `volumes:` mapping in
`docker-compose.yml`.

Tear down (keep data):

```bash
docker compose down
```

Tear down and wipe graph data:

```bash
docker compose down -v
```

---

## 3. Behind a real domain / TLS

`docker-compose.yml` exposes plain HTTP. For production put a TLS-terminating
reverse proxy (Caddy, Traefik, nginx, a cloud LB) in front of the `frontend`
container, and ensure WebSocket upgrades are forwarded for `/ws`. nginx example:

```nginx
location /ws {
    proxy_pass http://frontend:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

The bundled `docker/nginx.conf` already forwards `/api` and upgrades `/ws` to the
`collab` service inside the compose network.

---

## 4. Outbound LLM calls behind a proxy

The hub honors `HTTPS_PROXY` / `HTTP_PROXY` (its `dev`/`start` scripts set
`NODE_USE_ENV_PROXY=1`, and it installs an undici `ProxyAgent` when a proxy var is
present). Pass the proxy through `.env`:

```env
HTTPS_PROXY=http://user:pass@host:port
```

---

## 5. Scaling / multi-process

For more than one hub process (or restart-safe sessions), set `REDIS_URL` in
`.env` and add a Redis service to the compose file. Without it, the hub uses an
in-memory op-log (single process).

---

## 6. Health & logs

```bash
docker compose ps
docker compose logs -f collab
docker compose logs -f frontend
```

The hub logs `graph-collab-service listening on :4001 (graphs: …)` on a healthy
start.
