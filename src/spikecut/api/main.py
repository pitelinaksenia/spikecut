from fastapi import FastAPI

app = FastAPI(title="spikecut")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
