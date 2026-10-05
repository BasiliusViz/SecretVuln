# Helm chart для SecretVuln

**Отложен (2026-10-05)**: Kubernetes пока не нужен. Dockerfile для backend/frontend ещё нет — их делать первым шагом при реальном деплое (сервер с docker compose или кластер).

Планировалось: Планируемая структура:

```
deploy/helm/secretvuln/
  Chart.yaml
  values.yaml
  templates/
    api-deployment.yaml      # FastAPI (uvicorn)
    worker-deployment.yaml   # ARQ worker
    frontend-deployment.yaml # nginx со статикой
    ingress.yaml
    configmap.yaml
    secrets.yaml
    migrations-job.yaml      # alembic upgrade head (Helm hook pre-install/pre-upgrade)
```

Зависимости (subchart или внешние): PostgreSQL, Redis, MinIO/S3.
Для разработки используется docker-compose.yml в корне репозитория.
