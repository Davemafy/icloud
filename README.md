# Institutional SMC Cloud v3.5

GitHub/Railway-ready cloud service for the demo/paper Institutional SMC project.

## Railway deployment

1. Create/connect a Railway service to this private GitHub repository.
2. Attach a Railway Volume at `/data`.
3. Add variables from `.env.example` in Railway Variables. Keep `PAPER_ONLY=true` while testing.
4. Set `DATABASE_PATH=/data/smc_cloud.db`.
5. Deploy. The Dockerfile starts Uvicorn on Railway's injected `$PORT`.
6. Set the healthcheck path to `/health` and generate a public HTTPS domain.
7. In MT5, whitelist that base HTTPS URL and use the same base URL in DataBridge and Sequence EA.
8. `CLOUD_EA_API_KEY` in Railway must exactly match `CloudApiKey` in both MT5 EAs.

Do not commit `.env`, API keys, SQLite databases, or virtual environments.

## Local test

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

Run locally:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
