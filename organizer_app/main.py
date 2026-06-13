from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .agent import AgentRunError, AgentRunner
from .config import get_settings
from .storage import OrganizerStorage

settings = get_settings()
storage = OrganizerStorage(settings.data_root)
agent_runner = AgentRunner(settings.agent_command)

app = FastAPI(title="Local Organizer")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    status: str = "",
    error: str = "",
) -> HTMLResponse:
    return render_dashboard(request, q=q, status=status, error=error)


@app.get("/notes/{slug}", response_class=HTMLResponse)
def note_detail(
    request: Request,
    slug: str,
    q: str = "",
    status: str = "",
    error: str = "",
) -> HTMLResponse:
    return render_dashboard(request, selected_note_slug=slug, q=q, status=status, error=error)


@app.get("/meetings/{meeting_id}", response_class=HTMLResponse)
def meeting_detail(
    request: Request,
    meeting_id: str,
    q: str = "",
    status: str = "",
    error: str = "",
) -> HTMLResponse:
    return render_dashboard(request, selected_meeting_id=meeting_id, q=q, status=status, error=error)


@app.get("/api/dashboard")
def dashboard() -> JSONResponse:
    return JSONResponse(
        {
            "notes": [
                {
                    "slug": note.slug,
                    "title": note.title,
                    "body": note.body,
                    "created_at": note.created_at.isoformat(),
                    "updated_at": note.updated_at.isoformat(),
                    "tags": note.tags,
                }
                for note in storage.list_notes()
            ],
            "meetings": [
                {
                    "meeting_id": meeting.meeting_id,
                    "title": meeting.title,
                    "created_at": meeting.created_at.isoformat(),
                    "updated_at": meeting.updated_at.isoformat(),
                    "transcript": meeting.transcript,
                    "summary": meeting.summary,
                    "attendees": meeting.attendees,
                    "source_files": meeting.source_files,
                }
                for meeting in storage.list_meetings()
            ],
            "agent_configured": agent_runner.configured,
        }
    )


@app.post("/notes")
async def create_note(
    title: str = Form(""),
    body: str = Form(""),
    tags: str = Form(""),
) -> RedirectResponse:
    note = storage.create_note(title=title, body=body, tags=parse_csv(tags))
    return RedirectResponse(f"/notes/{note.slug}?status=Note+saved", status_code=303)


@app.post("/notes/{slug}")
async def update_note(
    slug: str,
    title: str = Form(""),
    body: str = Form(""),
    tags: str = Form(""),
) -> RedirectResponse:
    note = storage.update_note(slug=slug, title=title, body=body, tags=parse_csv(tags))
    return RedirectResponse(f"/notes/{note.slug}?status=Note+updated", status_code=303)


@app.post("/meetings")
async def create_meeting(
    title: str = Form(""),
    transcript: str = Form(""),
    attendees: str = Form(""),
    transcript_file: UploadFile | None = File(default=None),
) -> RedirectResponse:
    transcript_text, source_paths = await collect_uploaded_files([transcript_file], transcript.strip())
    source_path = source_paths[0] if source_paths else None
    if not transcript_text:
        raise HTTPException(status_code=400, detail="Transcript text or file is required")
    meeting = storage.create_meeting(
        title=title,
        transcript=transcript_text,
        attendees=parse_csv(attendees),
        source_path=source_path,
    )
    return RedirectResponse(f"/meetings/{meeting.meeting_id}?status=Meeting+saved", status_code=303)


@app.post("/meetings/{meeting_id}")
async def update_meeting(
    meeting_id: str,
    title: str = Form(""),
    transcript: str = Form(""),
    attendees: str = Form(""),
    summary: str = Form(""),
    transcript_file: UploadFile | None = File(default=None),
    attachment_files: list[UploadFile] | None = File(default=None),
) -> RedirectResponse:
    current = storage.read_meeting(meeting_id)
    transcript_text, transcript_sources = await collect_uploaded_files([transcript_file], transcript.strip())
    transcript_value = transcript_text or current.transcript
    extra_attachments = await collect_attachment_paths(attachment_files or [])
    all_attachments = transcript_sources + extra_attachments
    storage.update_meeting(
        meeting_id,
        title=title,
        transcript=transcript_value,
        attendees=parse_csv(attendees),
        summary=summary,
        attachment_paths=all_attachments,
    )
    return RedirectResponse(f"/meetings/{meeting_id}?status=Meeting+updated", status_code=303)


@app.post("/process/note/{slug}")
def process_note(slug: str) -> RedirectResponse:
    prompt = storage.build_note_prompt(slug)
    try:
        result = agent_runner.run(prompt)
        storage.write_agent_output("note", slug, result.output)
        storage.write_agent_run_log("note", slug, result=result)
        return RedirectResponse(f"/notes/{slug}?status=Agent+output+saved", status_code=303)
    except AgentRunError as exc:
        storage.write_agent_run_log("note", slug, error=exc)
        return RedirectResponse(f"/notes/{slug}?error={message_to_query(str(exc))}", status_code=303)


@app.post("/process/meeting/{meeting_id}")
def process_meeting(meeting_id: str) -> RedirectResponse:
    prompt = storage.build_meeting_prompt(meeting_id)
    try:
        result = agent_runner.run(prompt)
        storage.update_meeting_summary(meeting_id, result.output)
        storage.write_agent_output("meeting", meeting_id, result.output)
        storage.write_agent_run_log("meeting", meeting_id, result=result)
        return RedirectResponse(f"/meetings/{meeting_id}?status=Agent+output+saved", status_code=303)
    except AgentRunError as exc:
        storage.write_agent_run_log("meeting", meeting_id, error=exc)
        return RedirectResponse(f"/meetings/{meeting_id}?error={message_to_query(str(exc))}", status_code=303)


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def collect_uploaded_files(
    uploads: list[UploadFile | None],
    fallback_text: str = "",
) -> tuple[str, list[Path]]:
    transcript_text = fallback_text
    saved_paths: list[Path] = []
    for upload in uploads:
        if upload is None or not upload.filename:
            continue
        saved_path = await save_upload_to_inbox(upload)
        saved_paths.append(saved_path)
        if not transcript_text:
            transcript_text = saved_path.read_text(encoding="utf-8")
    return transcript_text.strip(), saved_paths


async def collect_attachment_paths(uploads: list[UploadFile]) -> list[Path]:
    saved_paths: list[Path] = []
    for upload in uploads:
        if not upload.filename:
            continue
        saved_paths.append(await save_upload_to_inbox(upload))
    return saved_paths


async def save_upload_to_inbox(upload: UploadFile) -> Path:
    filename = Path(upload.filename or "").name
    target = unique_inbox_path(filename)
    target.write_bytes(await upload.read())
    return target


def unique_inbox_path(filename: str) -> Path:
    candidate = storage.inbox_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        candidate = storage.inbox_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def render_dashboard(
    request: Request,
    *,
    selected_note_slug: str | None = None,
    selected_meeting_id: str | None = None,
    q: str = "",
    status: str = "",
    error: str = "",
) -> HTMLResponse:
    notes = storage.list_notes()
    meetings = storage.list_meetings()
    query = q.strip().lower()
    if query:
        notes = [
            note
            for note in notes
            if query in note.title.lower() or query in note.body.lower() or any(query in tag.lower() for tag in note.tags)
        ]
        meetings = [
            meeting
            for meeting in meetings
            if query in meeting.title.lower()
            or query in meeting.transcript.lower()
            or any(query in attendee.lower() for attendee in meeting.attendees)
        ]
    selected_note = storage.read_note(selected_note_slug) if selected_note_slug else None
    selected_meeting = storage.read_meeting(selected_meeting_id) if selected_meeting_id else None
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "notes": notes,
            "meetings": meetings,
            "selected_note": selected_note,
            "selected_meeting": selected_meeting,
            "selected_note_agent_output": storage.read_agent_output("note", selected_note.slug) if selected_note else "",
            "selected_meeting_agent_output": storage.read_agent_output("meeting", selected_meeting.meeting_id)
            if selected_meeting
            else "",
            "agent_configured": agent_runner.configured,
            "data_root": str(settings.data_root),
            "query": q,
            "status_message": status,
            "error_message": error,
        },
    )


def message_to_query(message: str) -> str:
    return quote_plus(message)


def run_dev() -> None:
    reload_enabled = os.environ.get("ORGANIZER_RELOAD", "").lower() in {"1", "true", "yes", "on"}
    uvicorn.run("organizer_app.main:app", host=settings.host, port=settings.port, reload=reload_enabled)
