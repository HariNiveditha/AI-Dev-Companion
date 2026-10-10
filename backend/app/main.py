import contextlib

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# API routers
from app.api.projects import router as projects_router
from app.api.requirements import router as requirements_router
from app.api.artifacts import router as artifacts_router
from app.api.executions import router as executions_router
from app.api.reports import router as reports_router
from app.api.documentation import router as documentation_router

# Database connection
from app.db.mongodb import connect_to_mongo, close_mongo_connection


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    await connect_to_mongo()
    try:
        yield
    finally:
        await close_mongo_connection()


app = FastAPI(
    title="AI Software Engineering Assistant",
    description="AI-assisted software development, testing, analysis, reporting, and documentation.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(projects_router, prefix="/projects", tags=["Projects"])
app.include_router(requirements_router, prefix="/requirements", tags=["Requirements"])
app.include_router(artifacts_router, prefix="/artifacts", tags=["Code Artifacts"])
app.include_router(executions_router, tags=["Executions"])
app.include_router(reports_router)
app.include_router(documentation_router)


@app.get("/", tags=["Health"])
def read_root():
    return {
        "message": "Welcome to AI Software Engineering Assistant API",
        "status": "running",
    }


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy"}