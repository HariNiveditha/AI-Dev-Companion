# AI-Dev-Companion - Phases 1 to 8


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

### Phase 5: Static and Security Analysis

The generated-code editor provides `Run Static Analysis`, which calls `POST /artifacts/{artifact_id}/analyze`. Checkstyle analyzes source formatting and coding style, SpotBugs analyzes compiled bytecode when compilation succeeds, and Semgrep runs configured Java security rules against source files. Findings are parsed from the tools, displayed by category, and persisted in the database. Tool-unavailable and not-run states are reported explicitly rather than fabricating findings.

### Phase 6: AI Test Case Generation

The system generates test cases from confirmed software requirements using the AI provider. Generated cases include a title, description, input, expected output, priority, and test type. The backend persists test cases and exposes endpoints to generate and retrieve them. The React frontend allows users to generate and view test cases.

Generated test cases are natural-language test specifications; they are not automatically executable Java/JUnit tests.

### Phase 7: Test Execution Lifecycle

The system provides execution-run models and API lifecycle handling for creating and retrieving execution records. Execution records include requirement and artifact-version references where supported, status, timestamps, and structured result fields.

**Java/JUnit execution remains disabled by default.** A secure execution environment must be configured before untrusted generated code can be executed. The current lifecycle must not be described as actual Java test execution.

### Phase 8: Testing and Documentation

Automated backend tests cover the execution-run lifecycle. The frontend production build and Git whitespace checks have been run during development. Consult the latest test output and repository state when verifying the current version.

### Phase 7: automated execution records

The project now includes execution-run persistence alongside the existing code generation and static analysis workflow. Execution is deliberately disabled by default until a secure isolation mechanism is configured.

- The backend stores a run record with a unique `execution_id`, `requirement_id`, and exact artifact/version reference.
- Each run includes a `status`, timestamps, `test_results`, and optional `error_message` fields.
- The execution API is available for lifecycle and persistence work, but it intentionally does not run untrusted Java directly on the host.
- When no secure sandbox is available, the API returns a clear disabled-state response explaining that Java/JUnit execution is unavailable until Docker/Podman or another isolated runner is configured.

Environment variable:

- `ENABLE_JAVA_EXECUTION=false` by default
- Set it to `true` only when a real, secure sandboxed Java/JUnit execution environment is available.

### Known Limitations

- Local development can use Mock MongoDB (`mongomock_motor`) without Docker. Mock data may reset when the backend restarts. Real MongoDB requires appropriate configuration and a running database. Set `USE_MOCK_MONGO=false` when using a configured real MongoDB instance.
- Java compilation requires a JDK with `javac` available on `PATH`.
- Static analysis depends on Checkstyle, SpotBugs, and Semgrep being installed and configured. Checkstyle and SpotBugs may be installed under `backend/.tools` or configured through environment variables, while Semgrep must be available in the active Python environment.
- Secure Docker-based sandbox execution is not configured. Java/JUnit execution is intentionally disabled unless a secure sandboxed execution mechanism is configured. Direct subprocess execution is not considered a secure sandbox.
- AI-generated test cases are stored as natural-language validation specifications and require conversion to executable tests before automated test execution is possible.
- The execution workflow currently focuses on persistence and lifecycle management. Untrusted generated Java must not be executed directly on the host. Set `ENABLE_JAVA_EXECUTION=true` only after a real, secure isolated execution environment has been configured and verified.
