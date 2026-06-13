from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .agent import AgentRunError, AgentRunResult
from .models import Meeting, Note


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "untitled"


class OrganizerStorage:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.notes_dir = data_root / "notes"
        self.meetings_dir = data_root / "meetings"
        self.inbox_dir = data_root / "inbox"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for path in (self.data_root, self.notes_dir, self.meetings_dir, self.inbox_dir):
            path.mkdir(parents=True, exist_ok=True)

    def list_notes(self) -> list[Note]:
        notes = []
        for path in sorted(self.notes_dir.glob("*.md"), reverse=True):
            notes.append(self.read_note(path.stem))
        return sorted(notes, key=lambda note: note.updated_at, reverse=True)

    def read_note(self, slug: str) -> Note:
        path = self.notes_dir / f"{slug}.md"
        raw = path.read_text(encoding="utf-8")
        metadata, body = self._parse_front_matter(raw)
        return Note(
            slug=slug,
            title=metadata["title"],
            body=body,
            created_at=from_iso(metadata["created_at"]),
            updated_at=from_iso(metadata["updated_at"]),
            tags=list(metadata.get("tags", [])),
        )

    def create_note(self, title: str, body: str, tags: list[str] | None = None) -> Note:
        title = title.strip() or "Untitled"
        slug_base = slugify(title)
        slug = slug_base
        counter = 2
        while (self.notes_dir / f"{slug}.md").exists():
            slug = f"{slug_base}-{counter}"
            counter += 1
        now = utc_now()
        note = Note(
            slug=slug,
            title=title,
            body=body.strip(),
            created_at=now,
            updated_at=now,
            tags=tags or [],
        )
        self._write_note(note)
        return note

    def update_note(self, slug: str, title: str, body: str, tags: list[str] | None = None) -> Note:
        existing = self.read_note(slug)
        note = Note(
            slug=existing.slug,
            title=title.strip() or existing.title,
            body=body.strip(),
            created_at=existing.created_at,
            updated_at=utc_now(),
            tags=tags or existing.tags,
        )
        self._write_note(note)
        return note

    def _write_note(self, note: Note) -> None:
        front_matter = {
            "title": note.title,
            "created_at": to_iso(note.created_at),
            "updated_at": to_iso(note.updated_at),
            "tags": note.tags,
        }
        payload = f"---\n{yaml.safe_dump(front_matter, sort_keys=False).strip()}\n---\n\n{note.body}\n"
        (self.notes_dir / f"{note.slug}.md").write_text(payload, encoding="utf-8")

    def note_path(self, slug: str) -> Path:
        return self.notes_dir / f"{slug}.md"

    def list_meetings(self) -> list[Meeting]:
        meetings = []
        for path in sorted(self.meetings_dir.iterdir()):
            if path.is_dir() and (path / "metadata.yml").exists():
                meetings.append(self.read_meeting(path.name))
        return sorted(meetings, key=lambda meeting: meeting.updated_at, reverse=True)

    def read_meeting(self, meeting_id: str) -> Meeting:
        meeting_dir = self.meetings_dir / meeting_id
        metadata = yaml.safe_load((meeting_dir / "metadata.yml").read_text(encoding="utf-8")) or {}
        transcript = (meeting_dir / "transcript.txt").read_text(encoding="utf-8") if (meeting_dir / "transcript.txt").exists() else ""
        summary = (meeting_dir / "summary.md").read_text(encoding="utf-8") if (meeting_dir / "summary.md").exists() else ""
        return Meeting(
            meeting_id=meeting_id,
            title=metadata["title"],
            created_at=from_iso(metadata["created_at"]),
            updated_at=from_iso(metadata["updated_at"]),
            transcript=transcript,
            summary=summary,
            attendees=list(metadata.get("attendees", [])),
            source_files=list(metadata.get("source_files", [])),
        )

    def create_meeting(
        self,
        title: str,
        transcript: str,
        attendees: list[str] | None = None,
        source_path: Path | None = None,
    ) -> Meeting:
        title = title.strip() or self._meeting_title_from_source(source_path)
        meeting_id = f"{utc_now().strftime('%Y%m%d-%H%M%S')}-{slugify(title)[:32]}"
        meeting_dir = self.meetings_dir / meeting_id
        meeting_dir.mkdir(parents=True, exist_ok=False)
        now = utc_now()
        source_files: list[str] = []
        if source_path is not None and source_path.exists():
            source_files.extend(self._copy_attachments(meeting_dir, [source_path]))
        metadata = {
            "title": title,
            "created_at": to_iso(now),
            "updated_at": to_iso(now),
            "attendees": attendees or [],
            "source_files": source_files,
        }
        (meeting_dir / "metadata.yml").write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
        (meeting_dir / "transcript.txt").write_text(transcript.strip(), encoding="utf-8")
        (meeting_dir / "summary.md").write_text("", encoding="utf-8")
        return self.read_meeting(meeting_id)

    def update_meeting(
        self,
        meeting_id: str,
        *,
        title: str,
        transcript: str,
        attendees: list[str] | None = None,
        summary: str | None = None,
        attachment_paths: list[Path] | None = None,
    ) -> Meeting:
        meeting_dir = self.meeting_dir(meeting_id)
        metadata = yaml.safe_load((meeting_dir / "metadata.yml").read_text(encoding="utf-8")) or {}
        metadata["title"] = title.strip() or metadata.get("title") or "Untitled Meeting"
        metadata["updated_at"] = to_iso(utc_now())
        metadata["attendees"] = attendees or []
        source_files = list(metadata.get("source_files", []))
        if attachment_paths:
            source_files.extend(self._copy_attachments(meeting_dir, attachment_paths))
        metadata["source_files"] = source_files
        (meeting_dir / "metadata.yml").write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
        (meeting_dir / "transcript.txt").write_text(transcript.strip() + "\n", encoding="utf-8")
        if summary is not None:
            (meeting_dir / "summary.md").write_text(summary.strip() + "\n", encoding="utf-8")
        return self.read_meeting(meeting_id)

    def update_meeting_summary(self, meeting_id: str, summary: str) -> Meeting:
        meeting_dir = self.meetings_dir / meeting_id
        metadata = yaml.safe_load((meeting_dir / "metadata.yml").read_text(encoding="utf-8")) or {}
        metadata["updated_at"] = to_iso(utc_now())
        (meeting_dir / "metadata.yml").write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
        (meeting_dir / "summary.md").write_text(summary.strip() + "\n", encoding="utf-8")
        return self.read_meeting(meeting_id)

    def meeting_dir(self, meeting_id: str) -> Path:
        return self.meetings_dir / meeting_id

    def write_agent_output(self, item_kind: str, item_id: str, output: str) -> Path:
        if item_kind == "note":
            target_dir = self.notes_dir / "_agent"
            target_name = f"{item_id}.md"
        else:
            target_dir = self.meetings_dir / item_id
            target_name = "agent-output.md"
        target_dir.mkdir(parents=True, exist_ok=True)
        output_path = target_dir / target_name
        output_path.write_text(output.strip() + "\n", encoding="utf-8")
        return output_path

    def read_agent_output(self, item_kind: str, item_id: str) -> str:
        if item_kind == "note":
            path = self.notes_dir / "_agent" / f"{item_id}.md"
        else:
            path = self.meetings_dir / item_id / "agent-output.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_agent_run_log(
        self,
        item_kind: str,
        item_id: str,
        result: AgentRunResult | None = None,
        error: AgentRunError | None = None,
    ) -> Path:
        if item_kind == "note":
            target_dir = self.notes_dir / "_agent"
            target_name = f"{item_id}.run.yml"
        else:
            target_dir = self.meetings_dir / item_id
            target_name = "agent-run.yml"
        target_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": to_iso(utc_now()),
            "status": "ok" if error is None else "error",
            "command": result.command if result else error.command if error else None,
            "returncode": result.returncode if result else error.returncode if error else None,
            "stdout": result.stdout if result else error.stdout if error else "",
            "stderr": result.stderr if result else error.stderr if error else "",
            "output_preview": result.output if result else "",
            "message": "" if error is None else str(error),
        }
        log_path = target_dir / target_name
        log_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return log_path

    def build_note_prompt(self, slug: str) -> str:
        note = self.read_note(slug)
        existing_output = self.read_agent_output("note", slug).strip()
        return (
            "You are processing a local organizer note.\n\n"
            f"Title: {note.title}\n"
            f"Tags: {', '.join(note.tags) or 'none'}\n"
            f"Created: {to_iso(note.created_at)}\n"
            f"Updated: {to_iso(note.updated_at)}\n\n"
            "Note body:\n"
            f"{note.body}\n\n"
            "Previous agent output:\n"
            f"{existing_output or 'none'}\n"
        )

    def build_meeting_prompt(self, meeting_id: str) -> str:
        meeting = self.read_meeting(meeting_id)
        attachment_list = "\n".join(f"- {path}" for path in meeting.source_files) or "- none"
        return (
            "You are processing a local organizer meeting.\n\n"
            f"Title: {meeting.title}\n"
            f"Attendees: {', '.join(meeting.attendees) or 'unknown'}\n"
            f"Created: {to_iso(meeting.created_at)}\n\n"
            "Return:\n"
            "- a concise summary\n"
            "- decisions\n"
            "- action items with owners if available\n"
            "- follow-up questions\n\n"
            "Attached source files:\n"
            f"{attachment_list}\n\n"
            "Current summary:\n"
            f"{meeting.summary or 'none'}\n\n"
            "Transcript:\n"
            f"{meeting.transcript}\n"
        )

    def _parse_front_matter(self, raw: str) -> tuple[dict[str, Any], str]:
        if not raw.startswith("---\n"):
            raise ValueError("Note is missing YAML front matter")
        _, rest = raw.split("---\n", 1)
        metadata_raw, body = rest.split("\n---\n", 1)
        metadata = yaml.safe_load(metadata_raw) or {}
        return metadata, body.strip()

    def _copy_attachments(self, meeting_dir: Path, paths: list[Path]) -> list[str]:
        attachments_dir = meeting_dir / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for path in paths:
            if not path.exists():
                continue
            destination = attachments_dir / path.name
            if destination.exists():
                destination = attachments_dir / f"{destination.stem}-{utc_now().strftime('%H%M%S')}{destination.suffix}"
            shutil.copy2(path, destination)
            copied.append(str(destination.relative_to(self.data_root)))
        return copied

    def _meeting_title_from_source(self, source_path: Path | None) -> str:
        if source_path is not None and source_path.name:
            return source_path.stem.replace("-", " ").replace("_", " ").strip().title() or "Untitled Meeting"
        return f"Meeting {utc_now().strftime('%Y-%m-%d %H:%M')}"
