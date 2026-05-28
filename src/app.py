"""FastAPI application — runtime-agnostic."""
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import handlers
from src.adapters import factory
from src.config import config


app = FastAPI(title="StudyBot Workspace")

_allowed = ["*"] if config.cors_origins == "*" else [o.strip() for o in config.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ai_client = factory.make_ai()
storage = factory.make_storage()
userstore = factory.make_userstore()
vector_store = factory.make_vector()


from fastapi import Request

def _resolve_user_id(request: Request, x_user_id: str | None) -> str:
    aws_event = request.scope.get("aws.event")
    if aws_event:
        claims = aws_event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        # Cognito stores email as the username (since UsernameAttributes: email)
        email = claims.get("email") or claims.get("cognito:username", "")
        if email:
            # Strip @studybot.local to get the display username
            if "@studybot.local" in email:
                return email.split("@")[0]
            return email
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return x_user_id


def _require_success(result: dict, status_code: int = 400) -> dict:
    if "error" in result:
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


class AuthRequest(BaseModel):
    username: str
    password: str


class FolderCreateRequest(BaseModel):
    name: str


class FolderRenameRequest(BaseModel):
    name: str


class FolderDocumentsRequest(BaseModel):
    doc_ids: list[str]

class UploadUrlRequest(BaseModel):
    filename: str
    size: int = 0
    content_type: str = "application/octet-stream"


class SessionCreateRequest(BaseModel):
    title: str | None = None
    topic_id: str | None = None


class SessionMessageRequest(BaseModel):
    message: str
    topic_id: str | None = None


class TopicQuizRequest(BaseModel):
    question_count: int = Field(default=10, ge=1, le=25)


class TopicQuizSubmitRequest(BaseModel):
    question_count: int = Field(ge=1, le=25)
    score: int = Field(ge=0)
    total: int = Field(ge=1)
    session_id: str | None = None


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "backends": {
            "ai": config.ai_backend,
            "storage": config.storage_backend,
            "userstore": config.userstore_backend,
            "vector": config.vector_backend,
        },
    }


@app.get("/api/bank/documents")
def api_list_bank_documents(request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return handlers.handle_list_docs(_resolve_user_id(request, x_user_id), userstore)


@app.post("/api/bank/documents/upload")
async def api_upload_bank_document(request: Request, file: UploadFile = File(...), x_user_id: str | None = Header(default=None)) -> dict:
    user_id = _resolve_user_id(request, x_user_id)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    return handlers.handle_upload(
        user_id=user_id,
        filename=file.filename or "untitled",
        data=data,
        storage=storage,
        userstore=userstore,
    )


@app.post("/api/bank/documents/upload-url")
def api_get_bank_upload_url(req: UploadUrlRequest, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    user_id = _resolve_user_id(request, x_user_id)
    result = handlers.handle_upload_url(
        user_id=user_id,
        filename=req.filename.strip(),
        size=req.size,
        content_type=req.content_type.strip() or "application/octet-stream",
        storage=storage,
        userstore=userstore,
    )
    return _require_success(result)


@app.get("/api/folders")
def api_list_folders(request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return handlers.handle_list_folders(_resolve_user_id(request, x_user_id), userstore)


@app.post("/api/folders")
def api_create_folder(req: FolderCreateRequest, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Folder name is required")
    return _require_success(handlers.handle_create_folder(_resolve_user_id(request, x_user_id), req.name.strip(), userstore))


@app.patch("/api/folders/{folder_id}")
def api_rename_folder(folder_id: str, req: FolderRenameRequest, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Folder name is required")
    return _require_success(handlers.handle_rename_folder(_resolve_user_id(request, x_user_id), folder_id, req.name.strip(), userstore))


@app.get("/api/folders/{folder_id}")
def api_get_folder(folder_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(handlers.handle_get_folder(_resolve_user_id(request, x_user_id), folder_id, userstore), status_code=404)


@app.get("/api/folders/{folder_id}/documents")
def api_get_folder_documents(folder_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(handlers.handle_get_folder(_resolve_user_id(request, x_user_id), folder_id, userstore), status_code=404)


@app.post("/api/folders/{folder_id}/documents")
def api_add_documents_to_folder(folder_id: str, req: FolderDocumentsRequest, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    if not req.doc_ids:
        raise HTTPException(status_code=400, detail="At least one doc_id is required")
    return _require_success(handlers.handle_add_documents_to_folder(_resolve_user_id(request, x_user_id), folder_id, req.doc_ids, userstore))


@app.post("/api/folders/{folder_id}/topics/generate")
def api_generate_topics(folder_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(
        handlers.handle_generate_topics(_resolve_user_id(request, x_user_id), folder_id, ai_client, userstore, vector_store),
        status_code=404,
    )


@app.get("/api/folders/{folder_id}/topics")
def api_list_topics(folder_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(handlers.handle_list_topics(_resolve_user_id(request, x_user_id), folder_id, userstore), status_code=404)


@app.get("/api/folders/{folder_id}/dashboard")
def api_folder_dashboard(folder_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(handlers.handle_folder_dashboard(_resolve_user_id(request, x_user_id), folder_id, userstore), status_code=404)


@app.post("/api/folders/{folder_id}/sessions")
def api_create_chat_session(folder_id: str, req: SessionCreateRequest, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(
        handlers.handle_create_chat_session(_resolve_user_id(request, x_user_id), folder_id, req.title, req.topic_id, userstore),
        status_code=404,
    )


@app.get("/api/folders/{folder_id}/sessions")
def api_list_chat_sessions(folder_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(handlers.handle_list_chat_sessions(_resolve_user_id(request, x_user_id), folder_id, userstore), status_code=404)


@app.get("/api/sessions/{session_id}/messages")
def api_list_session_messages(session_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(handlers.handle_list_chat_messages(_resolve_user_id(request, x_user_id), session_id, userstore), status_code=404)


@app.post("/api/sessions/{session_id}/messages")
def api_send_session_message(session_id: str, req: SessionMessageRequest, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")
    return _require_success(
        handlers.handle_chat_message(
            user_id=_resolve_user_id(request, x_user_id),
            session_id=session_id,
            message=req.message.strip(),
            topic_id=req.topic_id,
            ai_client=ai_client,
            userstore=userstore,
            vector_store=vector_store,
            vector_backend=config.vector_backend,
            bedrock_kb_id=config.vector_bedrock_kb_id,
        ),
        status_code=404,
    )


@app.post("/api/topics/{topic_id}/quiz")
def api_generate_topic_quiz(topic_id: str, req: TopicQuizRequest, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(
        handlers.handle_topic_quiz(_resolve_user_id(request, x_user_id), topic_id, req.question_count, ai_client, userstore, vector_store),
        status_code=404,
    )


@app.post("/api/topics/{topic_id}/quiz/submit")
def api_submit_topic_quiz(topic_id: str, req: TopicQuizSubmitRequest, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    return _require_success(
        handlers.handle_topic_quiz_submit(
            user_id=_resolve_user_id(request, x_user_id),
            topic_id=topic_id,
            question_count=req.question_count,
            score=req.score,
            total=req.total,
            userstore=userstore,
            session_id=req.session_id,
        ),
        status_code=404,
    )


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
PAGES_DIR = FRONTEND_DIR / "pages"
ASSETS_DIR = FRONTEND_DIR / "assets"

if config.serve_frontend:
    if ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

    @app.get("/")
    def bank_page() -> FileResponse:
        return FileResponse(PAGES_DIR / "bank.html")

    @app.get("/config.js")
    def config_js() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "config.js")

    @app.get("/folder/{folder_id}")
    def folder_page(folder_id: str) -> FileResponse:
        return FileResponse(PAGES_DIR / "folder-workspace.html")

    @app.get("/folder/{folder_id}/workspace")
    def folder_workspace_page(folder_id: str) -> FileResponse:
        return FileResponse(PAGES_DIR / "folder-workspace.html")

    @app.get("/folder/{folder_id}/quiz")
    def folder_quiz_page(folder_id: str) -> FileResponse:
        return FileResponse(PAGES_DIR / "folder-quiz.html")

    @app.get("/folder/{folder_id}/dashboard")
    def folder_dashboard_page(folder_id: str) -> FileResponse:
        return FileResponse(PAGES_DIR / "folder-dashboard.html")


try:
    from mangum import Mangum

    handler = Mangum(app)
except ImportError:
    pass
