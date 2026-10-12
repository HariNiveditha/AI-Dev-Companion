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
from app.api.improvement import router as improvement_router

# Database connection
from app.db.mongodb import connect_to_mongo, close_mongo_connection
from app.api.executions import reconcile_interrupted_executions


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    await connect_to_mongo()
    try:
        # A PENDING/RUNNING execution can only exist if the backend died
        # mid-run (executions run synchronously). Mark them ERROR so no
        # record is ever left looking queued forever.
        try:
            interrupted = await reconcile_interrupted_executions()
            if interrupted:
                print(
                    f"⚠️  Marked {interrupted} interrupted execution(s) as ERROR "
                    "(interrupted by a backend restart)."
                )
        except Exception as exc:  # reconciliation must never block startup
            print(f"⚠️  Could not reconcile interrupted executions: {type(exc).__name__}")
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
app.include_router(improvement_router)


@app.get("/", tags=["Health"])
def read_root():
    return {
        "message": "Welcome to AI Software Engineering Assistant API",
        "status": "running",
    }


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy"}