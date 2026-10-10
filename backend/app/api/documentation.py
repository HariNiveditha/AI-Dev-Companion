from fastapi import APIRouter, HTTPException

from app.models.documentation import (
    DocumentationGenerateRequest,
    DocumentationGenerateResponse,
)
from app.services.documentation.service import (
    generate_project_documentation,
    get_project_documentation,
)

router = APIRouter(prefix="/documentation", tags=["Documentation"])


@router.post(
    "/generate",
    response_model=DocumentationGenerateResponse,
)
async def generate_documentation(
    request: DocumentationGenerateRequest,
):
    try:
        documentation = await generate_project_documentation(
            project_id=request.project_id,
            document_type=request.document_type,
        )

        return {
            "success": True,
            "message": "Documentation generated successfully.",
            "documentation": documentation,
        }

    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while generating documentation.",
        ) from exc


@router.get("/{project_id}")
async def list_project_documentation(project_id: str):
    try:
        documentation = await get_project_documentation(project_id)

        return {
            "success": True,
            "count": len(documentation),
            "documentation": documentation,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve project documentation.",
        ) from exc