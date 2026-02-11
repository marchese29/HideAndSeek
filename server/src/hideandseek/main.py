from fastapi import FastAPI

app = FastAPI(
    title="HideAndSeek",
    description="Geographic Hide and Seek game server",
    version="0.1.0",
)


@app.get("/")
async def root():
    return {"message": "Hello, HideAndSeek!"}


@app.get("/health")
async def health():
    return {"status": "ok"}
