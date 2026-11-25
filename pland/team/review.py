"""Record review verdicts against the exact shared files a teammate inspected."""

from __future__ import annotations

import hashlib
import os
import time
from difflib import unified_diff
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import TYPE_CHECKING, Any

from ..config import AgentSettings
from ..sandbox.policy import PathPolicy

if TYPE_CHECKING:
    from ..agent import Agent
    from .board import TaskBoard

MAX_REVIEW_SECONDS = 900
MAX_REVIEW_FILE_BYTES = 8 * 1024 * 1024
MAX_TEXT_SNAPSHOT_BYTES = 64 * 1024
MAX_DIFF_CHARS = 12_000


def _shared_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name.startswith("shared/") or ".." in Path(name).parts:
        raise ValueError("review paths must start with shared/ and stay in the group's shared folder")
    path = PathPolicy({"": root, "shared": root}).resolve(name)
    if path == root:
        raise ValueError("review paths must stay in the group's shared folder")
    return path


def _read_file(path: Path) -> tuple[bytes, int]:
    if not path.is_file() or path.stat().st_size > MAX_REVIEW_FILE_BYTES:
        raise ValueError(f"{path.name}: review requires a regular file no larger than 8 MiB")
    with path.open("rb") as file:
        data = file.read(MAX_REVIEW_FILE_BYTES + 1)
        if len(data) > MAX_REVIEW_FILE_BYTES:
            raise ValueError(f"{path.name}: review file exceeds 8 MiB")
        return data, path.stat().st_mtime_ns


def _fingerprint(path: Path) -> tuple[str, int]:
    data, stamp = _read_file(path)
    return hashlib.sha256(data).hexdigest(), stamp


def signed_report_matches(root: Path, review: dict) -> bool:
    try:
        return _fingerprint(_shared_path(root, review["report"]))[0] == review.get("report_sha256")
    except (ValueError, OSError, RuntimeError):
        return False


def public_review(review: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in review.items() if k != "folder" and not k.startswith("_")}


def prepare_review(root: Path, spec: dict[str, Any], previous: dict[str, Any] | None = None, *,
                   step_limit: int = AgentSettings.review_max_steps,
                   time_limit: int = AgentSettings.review_timeout_seconds,
                   included: tuple[str, ...] = (), previously_versioned: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("review must contain inputs and report")
    inputs, report = spec.get("inputs"), spec.get("report")
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 8:
        raise ValueError("review requires one to eight input files")
    if not all(isinstance(p, str) for p in inputs) or len(set(inputs)) != len(inputs):
        raise ValueError("review inputs must be distinct shared paths")
    inputs = list(dict.fromkeys([*inputs, *included]))
    if len(inputs) > 60:
        raise ValueError("split a review with more than 60 versioned files into independent scopes")
    if type(step_limit) is not int or not 1 <= step_limit <= 200:
        step_limit = AgentSettings.review_max_steps
    if type(time_limit) is not int or not 1 <= time_limit <= MAX_REVIEW_SECONDS:
        time_limit = AgentSettings.review_timeout_seconds
    steps = spec.get("max_steps", step_limit)
    seconds = spec.get("timeout_seconds", time_limit)
    if type(steps) is not int or not 1 <= steps <= 200:
        raise ValueError("review max_steps must be an integer between 1 and 200")
    if type(seconds) is not int or not 1 <= seconds <= MAX_REVIEW_SECONDS:
        raise ValueError(f"review timeout_seconds must be an integer between 1 and {MAX_REVIEW_SECONDS}")
    report_path = _shared_path(root, report)
    paths = {name: _shared_path(root, name) for name in inputs if isinstance(name, str)}
    if len(paths) != len(inputs) or len(set(paths.values())) != len(inputs) or report_path in paths.values():
        raise ValueError("review inputs must be distinct and cannot include the report")
    before = _fingerprint(report_path) if report_path.exists() else None
    hashes, texts = {}, {}
    for name, path in paths.items():
        if name in previously_versioned and not path.exists():
            hashes[name] = None  # Absence is the new version of a previously reviewed file.
            continue
        data, _ = _read_file(path)
        hashes[name] = hashlib.sha256(data).hexdigest()
        if len(data) <= MAX_TEXT_SNAPSHOT_BYTES and b"\x00" not in data:
            try:
                texts[name] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
    criterion = spec.get("criterion")
    if criterion is not None and (not isinstance(criterion, str) or not criterion.strip()):
        raise ValueError("review criterion must be a nonempty description of the requirement")
    observation = spec.get("observation")
    if observation is not None and (not isinstance(observation, str) or not observation.strip()):
        raise ValueError("review observation must describe the outcome that needs direct verification")
    review = {"criterion": criterion.strip() if criterion else None, "folder": str(root), "inputs": hashes, "_text": texts, "report": report, "_report_before": before,
              "_steps": min(steps, step_limit), "_seconds": min(seconds, time_limit)}
    if observation:
        review["observation"] = observation.strip()
    if (previous and previous.get("folder") == str(root) and previous["inputs"].keys() <= hashes.keys()
            and previous.get("criterion") == review["criterion"] and previous["verdict"] in {"pass", "fail"}):
        changed = [name for name, digest in hashes.items() if previous["inputs"].get(name) != digest]
        if previous["verdict"] == "pass" and previous.get("evidence", {}).get("basis") == "observed":
            review["_prior_evidence"] = previous["evidence"]
        if changed:
            review["changed_inputs"] = changed
            review["_changes"] = _diff(previous.get("_text", {}), texts, changed)
            if previous["verdict"] == "fail":
                review["_prior_findings"] = previous.get("_report_excerpt", "")
    return review


def _diff(old: dict[str, str], new: dict[str, str], paths: list[str]) -> dict[str, str]:
    changes = {}
    remaining = MAX_DIFF_CHARS
    for name in paths:
        if name in old and name in new:
            patch = "\n".join(unified_diff(old[name].splitlines(), new[name].splitlines(),
                                           fromfile=f"before/{name}", tofile=f"after/{name}", n=2, lineterm=""))
            if patch and len(patch) <= remaining:
                changes[name] = patch
                remaining -= len(patch)
    return changes


def changed_inputs(root: Path, review: dict[str, Any]) -> list[str]:
    changed = []
    for name, digest in review["inputs"].items():
        try:
            path = _shared_path(root, name)
            if digest is None and not path.exists():
                continue
            if digest is not None and _fingerprint(path)[0] == digest:
                continue
        except (OSError, ValueError, RuntimeError):
            pass
        changed.append(name)
    return changed


def review_file_state(root: Path, review: dict[str, Any]) -> tuple[bool, list[str]]:
    try:
        if str(root) != review["folder"]:
            return False, []
        changed = changed_inputs(root, review)
        if changed:
            return False, changed
        report = review.get("report_sha256")
        return (not report or _fingerprint(_shared_path(root, review["report"]))[0] == report), []
    except (OSError, ValueError, RuntimeError):
        return False, []


def reusable_review(board: TaskBoard, room_id: str, own: dict | None, review: dict) -> dict | None:
    """An identical file can have independent requirements, external evidence or different reviewers."""
    if review.get("fresh") or review.get("attached_context"):
        return None
    candidates = [own] if own else []
    if not own and review.get("explicit_criterion"):
        recent = sorted(board.reviewed(room_id), key=lambda card: card["updated"], reverse=True)
        candidates = (board.review_record(card["id"]) for card in recent
                      if card["review"].get("criterion") == review["criterion"])
    for rec in candidates:
        if (not rec or not rec.get("criterion") or rec["criterion"] != review["criterion"]
                or rec.get("inputs") != review["inputs"] or rec.get("folder") != review["folder"]
                or set(rec.get("supporting_files", [])) != set(review.get("supporting_files", []))
                or rec.get("observation") != review.get("observation")
                or rec.get("conflict_source") != review.get("conflict_source")
                or rec.get("_context") != review["_context"] or rec.get("reviewer") != review["reviewer"]
                or (rec is not own and not rec.get("explicit_criterion"))):
            continue
        if (not rec.get("fresh") and not rec.get("attached_context") and rec.get("report_sha256")
                and rec["verdict"] in {"pass", "fail"} and review_file_state(Path(review["folder"]), rec)[0]):
            return rec
        break  # a newer inconclusive/missing report cannot be replaced with an older PASS
    return None


def reuse_report(root: Path, record: dict[str, Any], wanted: str) -> dict[str, Any]:
    """Give the requesting card its own evidence file without replacing another report."""
    old = record.get("report")
    if not wanted or wanted == old or not str(wanted).startswith("shared/") or ".." in Path(wanted).parts:
        return record
    src, dst = _shared_path(root, old), _shared_path(root, wanted)
    if dst.exists():
        if _fingerprint(dst)[0] == record["report_sha256"]:
            return {**record, "report": wanted}
        raise ValueError(f"{wanted} already exists with different contents; choose another report path")
    data, _ = _read_file(src)
    if hashlib.sha256(data).hexdigest() != record["report_sha256"]:
        raise ValueError("The earlier review report changed during reuse; request a fresh check.")
    original = data.decode("utf-8", errors="replace")
    head = f"Verdict: {record['verdict'].upper()}"
    note = f"(Reused from {old}: no input file changed since that review, so it was not run again.)"
    # Keep the verdict, evidence and resolution together, including noncanonical but valid headers.
    if not record.get("evidence") and original.startswith(head + "\n"):
        body = original.partition("\n")[2]
        copy = f"{head}\n{note}\n{body}"
    else:
        copy = f"{original}\n\n{note}\n"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dst.open("x", encoding="utf-8") as output:
            output.write(copy)
    except FileExistsError:
        raise ValueError(f"{wanted} was created during reuse; choose another report path") from None
    return {**record, "report": wanted, "report_sha256": _fingerprint(dst)[0], "report_written": True}


def _report_field(line: str, field: str) -> str:
    name, separator, value = line.partition(":")
    return value.strip() if separator and name.strip().lower() == field else ""


def _report_decision(data: bytes, review: dict[str, Any]) -> dict[str, Any]:
    # Only a standalone header counts, optionally after a Markdown title.
    header, _, body = data.removeprefix(b"\xef\xbb\xbf").lstrip().partition(b"\n")
    if header.startswith(b"# "):
        header, _, body = body.lstrip().partition(b"\n")
    verdict = _report_field(header.decode("utf-8", errors="replace"), "verdict").lower()
    excerpt = body[:4000].decode("utf-8", errors="replace")
    lines = excerpt.strip().splitlines()
    decision = {"verdict": verdict, "_report_excerpt": excerpt}
    basis, _, detail = _report_field(lines[0] if lines else "", "evidence").partition("|")
    basis, detail = basis.strip().lower(), detail.strip()
    if basis:
        decision["evidence"] = {"basis": basis, "detail": detail}
    reason = ""
    if verdict not in {"pass", "fail", "incomplete"}:
        reason = ("Unrecognized verdict header. Put Verdict: PASS, Verdict: FAIL or Verdict: INCOMPLETE "
                  "on its own line at the top of the report (after an optional title).")
    elif verdict == "pass":
        if basis == "unavailable" or ((review.get("observation") or review.get("fresh")) and not (basis == "observed" and detail)):
            reason = ("PASS requires the line immediately after the verdict to be Evidence: observed | <action and "
                      "actual result>. Use the evidence already obtained, or leave INCOMPLETE if the outcome is unverified.")
        elif source := review.get("conflict_source"):
            resolution = _report_field(lines[1] if len(lines) > 1 else "", "resolution")
            if not resolution.replace(source, "").strip(" |:-"):
                reason = "The disputed conclusion needs a Resolution: line after Evidence citing its deciding source."
            else:
                decision["resolution"] = resolution if source in resolution else f"{resolution} [Source: {source}]"
    if reason:
        decision.update(verdict="incomplete", verdict_reason=reason)
    return decision


def review_write_feedback(review: dict[str, Any], paths: PathPolicy, filename: str) -> str:
    """Preview the same declaration the board will read, without signing it or hashing the inputs."""
    try:
        path = paths.resolve(filename)
        if path == _shared_path(Path(review["folder"]), review["report"]):
            data, _ = _read_file(path)
            return _report_decision(data, review).get("verdict_reason", "")
    except (OSError, ValueError, RuntimeError):
        pass  # Finalization reports an unreadable or changed file against the signed scope.
    return ""


def finish_review(root: Path, review: dict[str, Any], run_status: str) -> dict[str, Any]:
    decision = {"verdict": "incomplete", "verdict_reason": "The reviewer did not write a new verdict to the report."}
    report_written = False
    report_sha256 = None
    try:
        data, stamp = _read_file(_shared_path(root, review["report"]))
        fingerprint = hashlib.sha256(data).hexdigest(), stamp
        updated = bool(data) and fingerprint != review["_report_before"]
        checkpoint = bool(review.get("_checkpoint_sha") and fingerprint[0] == review["_checkpoint_sha"])
        if updated or checkpoint:
            report_written = True
            report_sha256 = fingerprint[0]
            decision = _report_decision(data, review)
            if not updated:
                decision.update(verdict="incomplete", verdict_reason="The continuation did not update the prior report.")
            elif decision["verdict"] == "incomplete":
                decision.setdefault("verdict_reason", "The reviewer explicitly left checks open.")
    except (OSError, ValueError, RuntimeError):
        decision["verdict_reason"] = "The review report is missing or unreadable."
    if run_status != "completed":
        decision.update(verdict="incomplete", verdict_reason=f"The reviewer stopped before completing the review ({run_status}).")
    if not review_file_state(root, review)[0]:
        decision.update(verdict="stale", verdict_reason="The recorded file versions no longer match the review.")
    if decision["verdict"] != "pass":
        decision.pop("resolution", None)
    excerpt = decision.pop("_report_excerpt", "")
    return {**{k: v for k, v in review.items() if k not in {"_report_before", "_changes", "_prior_findings", "_prior_evidence", "_resume_notes", "_checkpoint_sha", "_context_changed"}},
            **decision, "report_written": report_written, "report_sha256": report_sha256, "stop_reason": run_status,
            "_report_excerpt": excerpt if decision["verdict"] in {"fail", "incomplete"} else ""}


class ReviewTurn:
    """Close versioned reviews before publishing the lead's reply for one group turn."""

    def __init__(self, board: TaskBoard, room_id: str, fast=None, *, user_text: str = ""):
        self.fast = fast
        self.board = board
        self.room_id = room_id
        self.user_text = user_text
        self.started = time.time()
        cards = board.list(room_id)
        self.previous = {c["id"] for c in cards if c.get("review", {}).get("verdict") in {"pass", "fail"}}
        self.touched: set[str] = set()
        # A follow-up in the same room inherits unresolved decisions until the lead explicitly
        # scopes an independent request. This also survives a service restart.
        self.inherited = {c["id"] for c in cards if c.get("conflict_source")
                          and (c["status"] != "done" or c.get("review", {}).get("verdict") != "pass")}
        self.conflicts = set(self.inherited)
        if fast:
            fast.inherited_conflicts = self.inherited.copy()
        self._learning = []
        self._lock = Lock()
        self.outputs: set[str] = set()
        # The lead may organize the shared folder after sign-off. Keep only this turn's
        # original evidence, so an accidental move can be repaired without another reviewer.
        self._reports: dict[str, tuple[str, str, bytes]] = {}

    @property
    def active(self) -> bool:
        return bool(self.previous or self.touched or self.conflicts or (self.fast and self.fast.has_active_checks()))

    def track(self, task_id: str) -> None:
        disputed = self.board.get(task_id).get("conflict_source")
        with self._lock:
            self.touched.add(task_id)
            if disputed:
                self.conflicts.add(task_id)

    def separate_request(self, task_id: str, reason: str) -> None:
        with self._lock:
            if not reason.strip() or task_id not in self.inherited or task_id in self.touched or task_id in self.user_text:
                raise ValueError("Only an untouched dispute from an earlier, independent request can be set aside; explain why.")
            self.conflicts.discard(task_id)
            if self.fast:
                self.fast.inherited_conflicts.discard(task_id)

    def unresolved(self) -> list[dict]:
        with self._lock:
            ids = tuple(self.conflicts)
        return [card for tid in ids if (card := self.board.get(tid))["status"] != "done"
                or card.get("review", {}).get("verdict") != "pass"]

    def defer_learning(self, agent, save, *, independently_sourced=False) -> None:
        # One delegate may discover a contradiction after a parallel sibling requests a save.
        with self._lock:
            self._learning.append((agent, save, independently_sourced))

    @staticmethod
    def _checks_pending(status: dict | None) -> bool:
        return bool(status and (status["pending"] or any(r["verdict"] != "pass" for r in status["requirements"])))

    def finish_learning(self, fast_status: dict | None = None) -> None:
        with self._lock:
            queued, self._learning = self._learning, []
        if not queued:
            return
        _, pending = self._reviews()
        unsettled = bool(self.conflicts or pending) or self._checks_pending(fast_status)
        for agent, save, sourced in queued:
            try:
                if unsettled and not sourced:
                    agent.emit("memory.withheld", reason="team conclusions lack independent verification")
                    continue
                save()
            except Exception as exc:
                agent.emit("memory.save_failed", error=str(exc))

    def keep_report(self, task_id: str, review: dict) -> None:
        name = review["report"]
        self._reports.pop(name, None)
        if review["verdict"] not in {"pass", "fail"}:
            return
        try:
            data, _ = _read_file(_shared_path(Path(review["folder"]), name))
            digest = hashlib.sha256(data).hexdigest()
            if digest == review["report_sha256"]:
                self._reports[name] = (task_id, digest, data)
        except (ValueError, OSError, RuntimeError):
            pass

    def restore_missing_report(self, task_id: str, review: dict) -> None:
        saved = self._reports.get(review["report"])
        if not saved or saved[:2] != (task_id, review.get("report_sha256")):
            return
        root = self.board.rt.rooms.shared_dir(self.room_id)
        try:
            if str(root) != review["folder"]:
                return
            path = _shared_path(root, review["report"])
            requested = root / review["report"].removeprefix("shared/")
            if path != requested or path.exists() or changed_inputs(root, review):
                return
            # Publish complete, original bytes without overwriting a concurrent edit.
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=path.parent) as tmp:
                tmp.write(saved[2])
                tmp.flush()
                os.link(tmp.name, path)
        except (ValueError, OSError, RuntimeError):
            pass  # the normal stale-evidence check still governs delivery

    def record_outputs(self, paths: list[str]) -> None:
        self.outputs.update(p for p in paths if p.startswith("shared/"))

    def _reviews(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        passed, pending = [], []
        for card in self.board.reviewed(self.room_id):
            review = card["review"]
            changed_this_turn = card["id"] in self.previous and review["verdict"] == "stale"
            if card["id"] in self.touched or card["id"] in self.conflicts or changed_this_turn:
                (passed if card["status"] == "done" and review["verdict"] == "pass" else pending).append(card)
        return passed, pending

    def _delivery_evidence(self, passed: list[dict[str, Any]], pending: list[dict[str, Any]]) -> str:
        root = self.board.rt.rooms.shared_dir(self.room_id)
        lines = ["Delivery is partial. Review status by scope:" if pending else "Acceptance evidence:"]
        for card in passed + pending:
            review = card["review"]
            paths = ", ".join(f"`{path}`" for path in review["inputs"])
            lines.append(f"- {review.get('criterion') or card['title']}: {review['verdict'].upper()} ({paths}).")
            if reason := review.get("verdict_reason"):
                lines.append(f"  {reason}")
            if review["verdict"] == "incomplete" and review.get("observation"):
                lines.append(f"  Required observation: {review['observation']}")
            if evidence := review.get("evidence"):
                if evidence["detail"]:
                    lines.append(f"  Evidence ({evidence['basis']}): {evidence['detail']}")
            if review["report_written"] and self._available(root, review["report"]):
                lines.append(f"  Review report: `{review['report']}`.")
        available = [p for p in sorted(self.outputs) if self._available(root, p)]
        if available and pending:
            lines.append("\nAvailable files (see review scopes above):")
            lines.extend(f"- `{path}`" for path in available)
        return "\n".join(lines)

    @staticmethod
    def _available(root: Path, path: str) -> bool:
        try:
            return _shared_path(root, path).is_file()
        except (OSError, ValueError, RuntimeError):
            return False

    def finalize(self, lead: Agent, draft: str, *, recheck: bool = True) -> str:
        from .delegation import DelegationError, delegate

        for task_id, _, _ in list(self._reports.values()):
            if record := self.board.review_record(task_id):
                self.restore_missing_report(task_id, record)
        passed, pending = self._reviews()
        if recheck:
            for card in pending:
                review = card["review"]
                stale = review["verdict"] == "stale" and review.get("changed_inputs")
                interrupted = (review["verdict"] == "incomplete" and review.get("stop_reason") in {"timeout", "max_iterations"}
                               and not review.get("resumes"))
                if not (stale or interrupted) or not card["assignee"]:
                    continue
                record = self.board.review_record(card["id"]) or {}
                if record.get("attached_context") and (not record.get("_attachments")
                                                       or record.get("_attachment_owner") != lead.profile.name):
                    continue  # only the original sender can reattach private evidence
                lead._check_cancel()
                try:
                    result, = delegate(lead._context(), [{
                        "task_id": card["id"], "to": card["assignee"],
                        "goal": review.get("criterion") or card["title"],
                        "context": record.get("_context", ""), "files": [p for p in record.get("_attachments", [])
                                     if p not in review["inputs"] or self._available(Path(record["folder"]), p)],
                        "review": {"inputs": [p for p in review["inputs"] if p not in review.get("supporting_files", [])][:8],
                                   "report": review["report"],
                                   **({"criterion": review["criterion"]} if review.get("criterion") else {}),
                                   **review.get("requested_limits", {})},
                    }])
                except DelegationError as exc:
                    result = {"status": "rejected", "error": str(exc)}
                lead.emit("review.recheck", task_id=card["id"], status=result["status"], error=result.get("error"))
            lead._check_cancel()
            passed, pending = self._reviews()
        fast_status = self.fast.status() if self.fast else None
        if conflicts := self.unresolved():
            details = "\n".join(f"- {c['id']}: {c['title']} — {c['description']} (source: {c['conflict_source']})"
                                for c in conflicts)
            return "Delivery is partial. Unresolved evidence conflicts:\n" + details + "\n" + self._delivery_evidence(passed, pending)
        if self._checks_pending(fast_status):
            evidence = self._delivery_evidence(passed, pending) if passed or pending else "Delivery is partial."
            return evidence + "\n" + self.fast.status_text(fast_status)
        if pending:
            return self._delivery_evidence(passed, pending)
        return draft + "\n\n" + self._delivery_evidence(passed, []) if passed else draft
