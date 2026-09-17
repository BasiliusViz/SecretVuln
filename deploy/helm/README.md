# Helm chart для SecretVuln

Пока не реализован. Планируемая структура:

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
