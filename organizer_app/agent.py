from __future__ import annotations

from dataclasses import dataclass
import subprocess
import tempfile
from pathlib import Path


@dataclass
class AgentRunResult:
    command: str
    input_path: Path
    output_path: Path
    output: str
    stdout: str
    stderr: str
    returncode: int


class AgentRunError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        command: str | None = None,
        stdout: str = "",
        stderr: str = "",
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class AgentRunner:
    def __init__(self, command_template: str | None) -> None:
        self.command_template = command_template

    @property
    def configured(self) -> bool:
        return bool(self.command_template)

    def run(self, prompt: str) -> AgentRunResult:
        if not self.command_template:
            raise AgentRunError("ORGANIZER_AGENT_COMMAND is not configured")

        with tempfile.TemporaryDirectory(prefix="organizer-agent-") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.txt"
            output_path = temp_path / "output.md"
            input_path.write_text(prompt, encoding="utf-8")
            try:
                command = self.command_template.format(input=str(input_path), output=str(output_path))
            except KeyError as exc:
                raise AgentRunError(
                    "Agent command template must only use {input} and {output} placeholders",
                ) from exc
            completed = subprocess.run(
                ["/bin/sh", "-lc", command],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise AgentRunError(
                    completed.stderr.strip() or completed.stdout.strip() or "Agent command failed",
                    command=command,
                    stdout=completed.stdout.strip(),
                    stderr=completed.stderr.strip(),
                    returncode=completed.returncode,
                )
            if output_path.exists():
                output = output_path.read_text(encoding="utf-8").strip()
            elif completed.stdout.strip():
                output = completed.stdout.strip()
            else:
                raise AgentRunError(
                    "Agent command completed without output",
                    command=command,
                    stdout=completed.stdout.strip(),
                    stderr=completed.stderr.strip(),
                    returncode=completed.returncode,
                )
            return AgentRunResult(
                command=command,
                input_path=input_path,
                output_path=output_path,
                output=output,
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
                returncode=completed.returncode,
            )
