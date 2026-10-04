from fastapi import FastAPI

app = FastAPI(title="Personal AI Hub", version="0.0.1")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "milestone": "M0", "privacy_default": "LOCAL_ONLY"}
