from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Note:
    slug: str
    title: str
    body: str
    created_at: datetime
    updated_at: datetime
    tags: list[str] = field(default_factory=list)


@dataclass
class Meeting:
    meeting_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    transcript: str
    summary: str
    attendees: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
