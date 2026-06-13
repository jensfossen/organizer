from __future__ import annotations

import argparse
from pathlib import Path

from .agent import AgentRunner
from .config import get_settings
from .storage import OrganizerStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="organizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    note_parser = subparsers.add_parser("note")
    note_parser.add_argument("title")
    note_parser.add_argument("--body", default="")
    note_parser.add_argument("--tags", default="")
    note_parser.add_argument("--process", action="store_true")

    meeting_parser = subparsers.add_parser("meeting")
    meeting_parser.add_argument("title", nargs="?", default="")
    meeting_parser.add_argument("--transcript-file", required=True)
    meeting_parser.add_argument("--attendees", default="")
    meeting_parser.add_argument("--process", action="store_true")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    storage = OrganizerStorage(settings.data_root)
    agent_runner = AgentRunner(settings.agent_command)

    if args.command == "note":
        note = storage.create_note(args.title, args.body, parse_csv(args.tags))
        if args.process:
            result = agent_runner.run(storage.build_note_prompt(note.slug))
            storage.write_agent_output("note", note.slug, result.output)
            storage.write_agent_run_log("note", note.slug, result=result)
        print(f"created note {note.slug}")
        return

    transcript_path = Path(args.transcript_file).expanduser().resolve()
    transcript = transcript_path.read_text(encoding="utf-8")
    meeting = storage.create_meeting(
        title=args.title,
        transcript=transcript,
        attendees=parse_csv(args.attendees),
        source_path=transcript_path,
    )
    if args.process:
        result = agent_runner.run(storage.build_meeting_prompt(meeting.meeting_id))
        storage.update_meeting_summary(meeting.meeting_id, result.output)
        storage.write_agent_output("meeting", meeting.meeting_id, result.output)
        storage.write_agent_run_log("meeting", meeting.meeting_id, result=result)
    print(f"created meeting {meeting.meeting_id}")


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
