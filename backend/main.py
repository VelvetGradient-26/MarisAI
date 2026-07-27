from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.insights import router as insights_router
from routers.marine import router as marine_router


app = FastAPI(title="MarisAI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(marine_router)
app.include_router(insights_router)


@app.get("/")
def healthcheck():
    return {"status": "ok"}
