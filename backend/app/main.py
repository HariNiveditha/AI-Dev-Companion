from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.projects import router as projects_router
from app.api.requirements import router as requirements_router
from app.db.mongodb import connect_to_mongo, close_mongo_connection
import contextlib

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()

app = FastAPI(title="AI Software Engineering Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router, prefix="/projects", tags=["projects"])
app.include_router(requirements_router, prefix="/requirements", tags=["requirements"])

@app.get("/")
def read_root():
    return {"message": "Welcome to AI Software Engineering Assistant API"}
