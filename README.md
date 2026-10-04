# AI Software Engineering Assistant - Phase 1

This repository contains Phase 1 setup for the AI Software Engineering Assistant project.

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
5.  Refresh the page and select the project again to verify the requirement is persisted.

### Known Limitations (Phase 1)
- Currently uses Mock MongoDB (`mongomock_motor`) for testing locally without docker, as Docker wasn't available in the test environment. Real MongoDB can be used by setting `USE_MOCK_MONGO=false` and running `docker compose up -d`.
- AI integrations and advanced features belong to later phases.
