from fastapi import FastAPI

from spikecut.api.routes import health

app = FastAPI(title="spikecut")

app.include_router(health.router)
