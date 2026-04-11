"""Deterministic repository audit runner.

The audit runner is intentionally strict about evidence:

- Every check is an explicit configured command.
- A check passes only when the command exits successfully.
- A check fails only on a non-zero exit code, timeout, or configured missing
  prerequisite.
- A check may be skipped when its configured prerequisite paths are absent, or
  when missing prerequisites are explicitly configured to skip.

There are no heuristic findings, severity guesses, or probabilistic rules here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

DEFAULT_CONFIG = "audit.toml"


class AuditConfigError(ValueError):
    """Raised when the audit configuration is invalid."""


CheckStatus = Literal["passed", "failed", "skipped"]
MissingPolicy = Literal["fail", "skip"]


@dataclass(frozen=True)
class CheckDefinition:
    """A single configured audit check."""

    id: str
    description: str
    enabled: bool
    required: bool
    cwd: Path
    args: tuple[str, ...]
    timeout_seconds: int
    tags: tuple[str, ...]
    requires_paths: tuple[Path, ...]
    requires_commands: tuple[str, ...]
    env: dict[str, str]
    missing_policy: MissingPolicy


@dataclass(frozen=True)
class CheckResult:
    """The outcome of a single audit check."""

    id: str
    status: CheckStatus
    description: str
    required: bool
    command: tuple[str, ...]
    cwd: str
    duration_seconds: float
    returncode: int | None
    reason: str | None
    stdout: str
    stderr: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _expand_tokens(value: str, tools: dict[str, str]) -> str:
    try:
        return value.format(**tools)
    except KeyError as exc:
        missing = exc.args[0]
        raise AuditConfigError(f"Unknown tool placeholder {{{missing}}} in audit config") from exc


def _resolve_path(root: Path, raw_path: str, tools: dict[str, str]) -> Path:
    path = Path(_expand_tokens(raw_path, tools))
    if path.is_absolute():
        return path
    return root / path


def _resolve_command(raw_command: str, root: Path, tools: dict[str, str]) -> str:
    command = _expand_tokens(raw_command, tools)
    if "/" in command:
        return str(_resolve_path(root, command, tools={}))
    return command


def _ensure_str_list(value: Any, field_name: str, check_id: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AuditConfigError(f"Check {check_id!r} field {field_name!r} must be a list of strings")
    return value


def load_checks(config_path: Path) -> list[CheckDefinition]:
    """Load and validate checks from a TOML config file."""
    root = config_path.resolve().parent
    with config_path.open("rb") as handle:
        raw_config = tomllib.load(handle)

    tools_raw = raw_config.get("tools", {})
    if not isinstance(tools_raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tools_raw.items()):
        raise AuditConfigError("Top-level [tools] table must contain string keys and values")
    tools = dict(tools_raw)

    raw_checks = raw_config.get("checks")
    if not isinstance(raw_checks, list):
        raise AuditConfigError("Config must contain at least one [[checks]] entry")

    definitions: list[CheckDefinition] = []
    seen_ids: set[str] = set()

    for raw_check in raw_checks:
        if not isinstance(raw_check, dict):
            raise AuditConfigError("Each [[checks]] entry must be a table")

        check_id = raw_check.get("id")
        if not isinstance(check_id, str) or not check_id:
            raise AuditConfigError("Each check must define a non-empty string id")
        if check_id in seen_ids:
            raise AuditConfigError(f"Duplicate check id {check_id!r}")
        seen_ids.add(check_id)

        description = raw_check.get("description", "")
        if not isinstance(description, str) or not description:
            raise AuditConfigError(f"Check {check_id!r} must define a non-empty string description")

        args_raw = raw_check.get("args")
        args_list = _ensure_str_list(args_raw, "args", check_id)
        if not args_list:
            raise AuditConfigError(f"Check {check_id!r} must define at least one command argument")

        timeout_seconds = raw_check.get("timeout_seconds", 300)
        if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
            raise AuditConfigError(f"Check {check_id!r} timeout_seconds must be a positive integer")

        enabled = raw_check.get("enabled", True)
        required = raw_check.get("required", True)
        if not isinstance(enabled, bool) or not isinstance(required, bool):
            raise AuditConfigError(f"Check {check_id!r} enabled/required must be booleans")

        cwd_raw = raw_check.get("cwd", ".")
        if not isinstance(cwd_raw, str):
            raise AuditConfigError(f"Check {check_id!r} cwd must be a string")

        tags = tuple(_ensure_str_list(raw_check.get("tags", []), "tags", check_id))
        requires_paths = tuple(
            _resolve_path(root, value, tools) for value in _ensure_str_list(raw_check.get("requires_paths", []), "requires_paths", check_id)
        )
        requires_commands = tuple(
            _resolve_command(value, root, tools) for value in _ensure_str_list(raw_check.get("requires_commands", []), "requires_commands", check_id)
        )

        env_raw = raw_check.get("env", {})
        if not isinstance(env_raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env_raw.items()):
            raise AuditConfigError(f"Check {check_id!r} env must be a table of string keys and values")
        env = {key: _expand_tokens(value, tools) for key, value in env_raw.items()}

        missing_policy = raw_check.get("missing_policy", "fail")
        if missing_policy not in {"fail", "skip"}:
            raise AuditConfigError(f"Check {check_id!r} missing_policy must be 'fail' or 'skip'")

        definitions.append(
            CheckDefinition(
                id=check_id,
                description=description,
                enabled=enabled,
                required=required,
                cwd=_resolve_path(root, cwd_raw, tools),
                args=tuple(_resolve_command(arg, root, tools) for arg in args_list),
                timeout_seconds=timeout_seconds,
                tags=tags,
                requires_paths=requires_paths,
                requires_commands=requires_commands,
                env=env,
                missing_policy=missing_policy,
            )
        )

    return definitions


def _command_exists(command: str) -> bool:
    if "/" in command:
        candidate = Path(command)
        return candidate.is_file() and os.access(candidate, os.X_OK)
    return shutil.which(command) is not None


def _matches_selector(check: CheckDefinition, selectors: set[str]) -> bool:
    return check.id in selectors or any(tag in selectors for tag in check.tags)


def select_checks(
    checks: list[CheckDefinition],
    only: set[str] | None = None,
    skip: set[str] | None = None,
) -> list[CheckDefinition]:
    """Filter checks by enabled flag and caller selectors."""
    selected = [check for check in checks if check.enabled]

    if only:
        selected = [check for check in selected if _matches_selector(check, only)]

    if skip:
        selected = [check for check in selected if not _matches_selector(check, skip)]

    return selected


def run_check(check: CheckDefinition) -> CheckResult:
    """Execute a single configured check."""
    start = time.perf_counter()

    missing_paths = [path for path in check.requires_paths if not path.exists()]
    if missing_paths:
        duration = time.perf_counter() - start
        return CheckResult(
            id=check.id,
            status="skipped",
            description=check.description,
            required=check.required,
            command=check.args,
            cwd=str(check.cwd),
            duration_seconds=duration,
            returncode=None,
            reason=f"required paths missing: {', '.join(str(path) for path in missing_paths)}",
            stdout="",
            stderr="",
        )

    missing_commands = [command for command in check.requires_commands if not _command_exists(command)]
    if missing_commands:
        duration = time.perf_counter() - start
        status: CheckStatus = "skipped" if check.missing_policy == "skip" else "failed"
        return CheckResult(
            id=check.id,
            status=status,
            description=check.description,
            required=check.required,
            command=check.args,
            cwd=str(check.cwd),
            duration_seconds=duration,
            returncode=None,
            reason=f"required commands missing: {', '.join(missing_commands)}",
            stdout="",
            stderr="",
        )

    executable = check.args[0]
    if not _command_exists(executable):
        duration = time.perf_counter() - start
        status = "skipped" if check.missing_policy == "skip" else "failed"
        return CheckResult(
            id=check.id,
            status=status,
            description=check.description,
            required=check.required,
            command=check.args,
            cwd=str(check.cwd),
            duration_seconds=duration,
            returncode=None,
            reason=f"command not found: {executable}",
            stdout="",
            stderr="",
        )

    env = os.environ.copy()
    env.update(check.env)

    try:
        completed = subprocess.run(
            list(check.args),
            cwd=check.cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=check.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - start
        return CheckResult(
            id=check.id,
            status="failed",
            description=check.description,
            required=check.required,
            command=check.args,
            cwd=str(check.cwd),
            duration_seconds=duration,
            returncode=None,
            reason=f"timed out after {check.timeout_seconds}s",
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        )

    duration = time.perf_counter() - start
    status: CheckStatus = "passed" if completed.returncode == 0 else "failed"
    return CheckResult(
        id=check.id,
        status=status,
        description=check.description,
        required=check.required,
        command=check.args,
        cwd=str(check.cwd),
        duration_seconds=duration,
        returncode=completed.returncode,
        reason=None if completed.returncode == 0 else f"command exited with {completed.returncode}",
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _parse_selectors(values: list[str]) -> set[str]:
    selectors: set[str] = set()
    for value in values:
        for part in value.split(","):
            selector = part.strip()
            if selector:
                selectors.add(selector)
    return selectors


def _format_command(command: tuple[str, ...]) -> str:
    rendered: list[str] = []
    for part in command:
        if any(char.isspace() for char in part):
            rendered.append(json.dumps(part))
        else:
            rendered.append(part)
    return " ".join(rendered)


def _print_check_list(checks: list[CheckDefinition]) -> None:
    for check in checks:
        tags = ", ".join(check.tags) if check.tags else "-"
        enabled = "enabled" if check.enabled else "disabled"
        required = "required" if check.required else "optional"
        print(f"{check.id}: {check.description}")
        print(f"  status: {enabled}, {required}")
        print(f"  tags: {tags}")
        print(f"  cwd: {check.cwd}")
        print(f"  cmd: {_format_command(check.args)}")


def _print_result(result: CheckResult, verbose: bool) -> None:
    label = result.status.upper()
    requirement = "required" if result.required else "optional"
    print(f"[{label}] {result.id} ({requirement}, {result.duration_seconds:.2f}s) - {result.description}")
    print(f"  cwd: {result.cwd}")
    print(f"  cmd: {_format_command(result.command)}")
    if result.reason:
        print(f"  reason: {result.reason}")
    if verbose and result.stdout.strip():
        print("  stdout:")
        print(result.stdout.rstrip())
    if verbose and result.stderr.strip():
        print("  stderr:")
        print(result.stderr.rstrip())


def _json_summary(results: list[CheckResult]) -> dict[str, Any]:
    failed_required = [result for result in results if result.status == "failed" and result.required]
    failed_optional = [result for result in results if result.status == "failed" and not result.required]
    passed = [result for result in results if result.status == "passed"]
    skipped = [result for result in results if result.status == "skipped"]
    return {
        "ok": not failed_required,
        "counts": {
            "passed": len(passed),
            "failed_required": len(failed_required),
            "failed_optional": len(failed_optional),
            "skipped": len(skipped),
            "total": len(results),
        },
        "results": [asdict(result) for result in results],
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Run deterministic repository audit checks")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"Path to the audit config file (default: {DEFAULT_CONFIG})")
    parser.add_argument("--list", action="store_true", help="List configured checks and exit")
    parser.add_argument("--only", action="append", default=[], help="Run only these check ids or tags (repeatable, comma-separated)")
    parser.add_argument("--skip", action="append", default=[], help="Skip these check ids or tags (repeatable, comma-separated)")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first required failing check")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and print selected checks without executing them")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    parser.add_argument("--verbose", action="store_true", help="Print captured stdout/stderr for each executed check")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = _repo_root() / config_path

    if not config_path.exists():
        parser.error(f"Audit config not found: {config_path}")

    try:
        checks = load_checks(config_path)
    except AuditConfigError as exc:
        print(f"Audit config error: {exc}", file=sys.stderr)
        return 2

    if args.list:
        _print_check_list(checks)
        return 0

    selected = select_checks(
        checks,
        only=_parse_selectors(args.only),
        skip=_parse_selectors(args.skip),
    )

    if not selected:
        print("No audit checks selected.", file=sys.stderr)
        return 2

    if args.dry_run:
        _print_check_list(selected)
        return 0

    results: list[CheckResult] = []
    for check in selected:
        result = run_check(check)
        results.append(result)
        if not args.json:
            _print_result(result, verbose=args.verbose)
        if args.fail_fast and result.status == "failed" and result.required:
            break

    summary = _json_summary(results)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        counts = summary["counts"]
        print(
            "Summary:"
            f" passed={counts['passed']}"
            f" failed_required={counts['failed_required']}"
            f" failed_optional={counts['failed_optional']}"
            f" skipped={counts['skipped']}"
            f" total={counts['total']}"
        )

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
