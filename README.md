# AI-Dev-Companion - Phases 1 through 5

This repository contains project and requirement setup, AI requirement analysis and confirmation, AI Java code generation, Java compilation, and real static/security analysis for confirmed requirements.

## Structure

*   `backend/` - FastAPI backend application.
*   `frontend/` - React TypeScript frontend application using Vite.
*   `docker-compose.yml` - Docker setup for MongoDB.

## Getting Started

### Prerequisites

*   Python 3.10+
*   Node.js 18+
*   (Optional) Docker Desktop if you want to run real MongoDB. By default, it runs with `mongomock_motor` if `USE_MOCK_MONGO=true`.

### Backend Setup

1.  Navigate to the `backend` folder: `cd backend`
2.  Create a virtual environment: `python -m venv venv`
3.  Activate it: `.\venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Mac/Linux)
4.  Install dependencies: `pip install -r requirements.txt`
5.  Install mock mongo (if testing without docker): `pip install mongomock_motor`
6.  Start server: `uvicorn app.main:app --reload` (Runs on port 8000)

### Frontend Setup

1.  Navigate to the `frontend` folder: `cd frontend`
2.  Install dependencies: `npm install`
3.  Start dev server: `npm run dev`

### Testing the flow

1.  Open the frontend application in your browser (usually http://localhost:5173).
2.  Create a project.
3.  Click on the newly created project in the list.
4.  Submit a requirement.
5. Analyze the requirement and review the AI analysis.
6. Confirm the requirement.
7. Generate Java code and review the generated artifacts.
8. Edit and save a generated Java file.
9. Compile the saved artifact and review the actual build result.
10. Run static analysis and review the Checkstyle, SpotBugs, and Security findings.
11. Refresh the page and select the project again to verify the requirement, analysis, confirmation, artifacts, and findings are persisted.

### Phase 3 Code Generation

Code generation requires a requirement with status `CONFIRMED`. The frontend calls `POST /requirements/{id}/generate-code`, which sends the confirmed requirement and stored AI analysis to Gemini, validates the structured Java response, and persists each generated file as a CodeArtifact in MongoDB. Generated files and their versions are displayed in the frontend, where a developer can save an edited version without overwriting earlier artifacts.

### Phase 4 Java Compilation

The generated-code editor provides a `Compile` action for saved Java artifacts. It calls `POST /artifacts/{artifact_id}/compile`, compiles the latest Java files for the artifact's requirement with `javac` in an isolated temporary workspace, and displays the real exit code, compiler output, and duration. Results use `PASSED`, `FAILED`, or `TOOL_ERROR` when a compiler is unavailable or compilation times out. Compilation does not approve or execute code.

### Phase 5 Static and Security Analysis

The generated-code editor provides `Run Static Analysis`, which calls `POST /artifacts/{artifact_id}/analyze`. Checkstyle analyzes source formatting and coding style, SpotBugs analyzes compiled bytecode when compilation succeeds, and Semgrep runs the configured Java security rules against source files. Findings are parsed from the real tools, displayed separately by category, and persisted in MongoDB. The analysis reports tool-unavailable and not-run states instead of fabricating findings.

### Known Limitations
- Currently uses Mock MongoDB (`mongomock_motor`) for testing locally without docker, as Docker wasn't available in the test environment. Real MongoDB can be used by setting `USE_MOCK_MONGO=false` and running `docker compose up -d`.
- Phase 4 compilation requires a JDK with `javac` on `PATH`. Docker sandbox compilation is not configured in this repository.
- Phase 5 requires Checkstyle and SpotBugs under `backend/.tools` or configured through environment variables, and Semgrep installed in the active Python environment. Docker sandboxing is not configured.
- Phase 6 and later workflow stages are not implemented.
