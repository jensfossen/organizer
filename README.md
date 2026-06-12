# Local Organizer

Local-first organizer system for:

- writing notes without Notion
- capturing meeting transcripts and attachments
- handing notes and meetings to a local agent such as Hermes or Codex

## What It Does

- Stores notes as Markdown files with YAML front matter
- Stores meetings in per-meeting folders with transcript, summary, and metadata
- Exposes a small local web UI for creating and browsing notes and meetings
- Supports transcript uploads from Whisper Flow, Voice Memos exports, or any other local transcription workflow
- Runs a configurable local agent command against a note or meeting and saves the output back into the organizer

## Project Layout

```text
data/
  notes/
  meetings/
  inbox/
organizer_app/
```

## Quick Start

1. Create a virtual environment and install dependencies:

```bash
cd /Users/jensfossen-macmini/organizer
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Optionally set an agent command:

```bash
export ORGANIZER_AGENT_COMMAND='hermes process "{input}" > "{output}"'
```

The command receives:

- `{input}`: a generated prompt file containing the note or meeting context
- `{output}`: the path where the agent should write its result

If your agent prints to stdout instead of writing files, wrap it in a shell command that redirects stdout to `{output}`.

3. Run the app:

```bash
organizer-dev
```

4. Open `http://127.0.0.1:8765`

By default, `organizer-dev` starts without filesystem watching so it stays compatible with locked-down local environments. If you want auto-reload and your machine allows file watching, run:

```bash
ORGANIZER_RELOAD=1 organizer-dev
```

## Suggested Workflow

1. Write notes directly in the UI or edit the Markdown files in `data/notes/`
2. Export meeting transcripts from Whisper Flow or another local transcription tool
3. Upload the transcript in the Meetings section
4. Click `Process` to send the meeting or note to Hermes/Codex
5. Review the generated summary and next actions locally

You can also process items from the CLI:

```bash
organizer note "Weekend plan" --body "Draft agenda" --process
organizer meeting "Team sync" --transcript-file ~/Desktop/transcript.txt --process
```

## Notes

- This first version does not perform speech-to-text itself. It assumes you already have a transcript or want to attach raw files for later processing.
- Data remains on disk in human-readable files.
- Agent runs save both the generated output and a human-readable YAML run log for troubleshooting local Hermes/Codex handoffs.
