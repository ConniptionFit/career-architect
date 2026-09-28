"""career-architect MCP server: the deterministic half of the `jobs` skill, hosted so any MCP client can use it through Obot.

Stateless by design. Every tool is a pure function of the text it is given: nothing is written to disk, nothing is kept
between calls, and request bodies are never logged (they hold a person's work history). The user's documents live in
their own Google Drive; the agent reads them there and passes text in. See docs/ARCHITECTURE.md.
In the deployment this is one component of a virtual MCP server named Jobs, next to Reactive Resume, Google Drive and Google Docs.

Run:  python server.py            (listens on $MCP_HOST:$MCP_PORT, default 0.0.0.0:8080, path /mcp)
Env:  CAREER_MCP_TOKEN            shared secret; when set every request except /healthz must send it as
                                  `Authorization: Bearer <token>` or `X-Career-Token: <token>`
      CAREER_MCP_ALLOWED_HOSTS    comma-separated Host header values accepted (DNS-rebinding protection)
      CAREER_MCP_ALLOW_UNSECURED  set to 1 to start without a token (local development only); otherwise a missing token is fatal
"""
from __future__ import annotations

import contextlib
import datetime as dt
import functools
import hmac
import io
import json
import logging
import os
import re
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Annotated, Any

HERE = Path(__file__).resolve().parent
for candidate in (HERE, HERE.parent / "jobs" / "scripts"):       # in the image career.py sits beside this file; in the repo it is under jobs/scripts
    if (candidate / "career.py").exists():
        sys.path.insert(0, str(candidate))
        break
import career  # noqa: E402
import yaml  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from pydantic import Field  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

SERVER_VERSION = "1.2.0"
log = logging.getLogger("career-mcp")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "WARNING").upper()
if LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    LOG_LEVEL = "WARNING"

# Limits keep one careless call from tying the service up. A 12-year career is about 55 KB of facts.
MAX_DOC = 250_000            # characters in any one document
MAX_DOCS = 40                # documents in one list
MAX_TOTAL = 600_000          # characters across one call
MAX_BODY = 2_000_000         # bytes in one HTTP request


# ---------------------------------------------------------------- the guide (the skill's own documents, served live)

def _guide_root() -> Path:
    """The skill folder: `jobs/` beside this file in the image, `../jobs` in the repository."""
    for candidate in (HERE / "jobs", HERE.parent / "jobs"):
        if (candidate / "SKILL.md").exists():
            return candidate
    raise RuntimeError("the skill documents (jobs/SKILL.md) were not found next to the server")


def _split_front(text: str) -> tuple[dict, str]:
    m = re.match(r"---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    try:
        return yaml.safe_load(m.group(1)) or {}, text[m.end():].lstrip("\n")
    except yaml.YAMLError:
        return {}, text[m.end():].lstrip("\n")


def _load_guide() -> tuple[dict[str, str], str]:
    """Every markdown document of the skill, keyed by its path inside the skill folder, and the skill's version. Read once at start:
    the documents are part of the image, so a deploy is what changes them."""
    root = _guide_root()
    docs = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.md"))}
    front, body = _split_front(docs["SKILL.md"])
    docs["SKILL.md"] = body
    return docs, str((front.get("metadata") or {}).get("version") or "")


GUIDE, GUIDE_VERSION = _load_guide()
START_TOPICS = ("", "start", "skill", "skill.md")


def guide_key(topic: str) -> str | None:
    """The key of the document a topic names ('start', 'workflows/score', 'references/storage.md', './jobs/style/voice'), or None.
    Only keys of the bundled documents match, so a topic can never reach any other file."""
    t = (topic or "").strip()
    if t.lower() in START_TOPICS:
        return "SKILL.md"
    t = re.sub(r"^(\./)?(jobs/)?", "", t)
    for key in (t, t + ".md"):
        if key in GUIDE:
            return key
    return None


# ---------------------------------------------------------------- input handling

def _text(name: str, value: Any, required: bool = True) -> str:
    if value is None or value == "":
        if required:
            raise ToolError(f"{name} is required")
        return ""
    if not isinstance(value, str):
        raise ToolError(f"{name} must be text")
    if len(value) > MAX_DOC:
        raise ToolError(f"{name} is {len(value):,} characters; the limit is {MAX_DOC:,}. Pass only the parts this call needs")
    try:
        return career.normalize_drive_text(value)        # Drive text arrives escaped or base64 encoded; clean text passes through unchanged
    except ValueError as e:
        raise ToolError(f"{name}: {e}")


def _docs(name: str, values: Any, required: bool = True) -> list[str]:
    if values is None or values == []:
        if required:
            raise ToolError(f"{name} is required")
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list) or len(values) > MAX_DOCS:
        raise ToolError(f"{name} must be a list of at most {MAX_DOCS} documents")
    out = [_text(f"{name}[{i}]", v) for i, v in enumerate(values)]
    if sum(map(len, out)) > MAX_TOTAL:
        raise ToolError(f"{name} is too large ({sum(map(len, out)):,} characters; the limit is {MAX_TOTAL:,})")
    return out


def _today(value: str | None) -> dt.date:
    if not value:
        return dt.datetime.now(dt.timezone.utc).date()
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ToolError("today must be YYYY-MM-DD")


def _yaml(name: str, text: str) -> Any:
    try:
        return career.load_yaml(text) or {}
    except yaml.YAMLError as e:
        first = str(e).splitlines()[0] if str(e) else "invalid YAML"
        raise ToolError(f"{name} is not valid YAML: {first}")


def _facts(name: str, docs: list[str]) -> dict:
    try:
        return career.merge_facts(docs)
    except (yaml.YAMLError, ValueError) as e:
        raise ToolError(f"{name}: {str(e).splitlines()[0]}")


def _profile(text: str) -> dict:
    try:
        profile = career.parse_front(text)
    except yaml.YAMLError as e:
        raise ToolError(f"profile is not valid YAML front matter: {str(e).splitlines()[0]}")
    if not isinstance(profile, dict):
        raise ToolError("profile front matter must be a YAML mapping")
    return profile


def _index(skills_md: str) -> dict:
    parsed = career.parse_skills_md(skills_md)
    if not parsed["idx"]:
        raise ToolError("skills_md has no skills table: pass the document written by build_index")
    return parsed


def _issues(rows) -> list[dict]:
    """The lint messages, with the one that means something different when only some roles are supplied made actionable."""
    out = []
    for level, where, msg in rows:
        msg = msg.replace("not in facts.md", "not in the facts you supplied (pass the role fragment that holds it)")
        out.append({"level": level, "where": where, "message": msg})
    return out


def _report(issues: list[dict]) -> dict:
    errors = sum(1 for i in issues if i["level"] == "E")
    return {"ok": errors == 0, "errors": errors, "warnings": len(issues) - errors, "issues": issues}


# ---------------------------------------------------------------- server

allowed_hosts = [h.strip() for h in os.environ.get("CAREER_MCP_ALLOWED_HOSTS", "career-architect-mcp:8080,localhost:8080,127.0.0.1:8080").split(",") if h.strip()]
server = MCPServer(
    name="career-architect",
    title="Career Architect",
    version=SERVER_VERSION,
    instructions=(
        "Deterministic checks for the `jobs` skill: score a job posting against a skills index, lint a tailored resume or cover letter "
        "against the person's recorded facts, and build the Reactive Resume patch. Stateless: pass the text of the person's documents "
        "(as read from Google Docs, unchanged) in every call; nothing is stored. Run these checks instead of judging by hand: a resume or "
        "letter that skipped them has not been checked against the person's facts. Begin every job-search task by calling `guide`: "
        "it returns the current instructions for the `jobs` skill (workflow, rules, storage protocol), so a client needs no other copy of them."
    ),
    log_level=LOG_LEVEL,        # the SDK configures logging itself at construction and defaults to INFO, which logs tool error messages
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
Doc = Annotated[str, Field(description="Document text exactly as read from the person's Google Doc (`markdown_content` of the Google Docs get_document tool), copied unchanged. It is cleaned automatically; text from other Drive readers (escaped, doubled or base64) also works.")]


def guarded(fn):
    """Turn a crash (a bug, not bad input) into a fixed message. The SDK would log the exception text, and that text can quote a
    person's documents, so only the tool name, the exception type and the stack frames (code, not data) are logged."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as e:
            log.error("tool %s crashed with %s (message withheld: it may quote the person's documents)\n%s",
                      fn.__name__, type(e).__name__, "".join(traceback.format_tb(e.__traceback__)))
            raise ToolError(f"internal error in {fn.__name__} ({type(e).__name__}); nothing was stored. Tell the administrator.") from None
    return wrapper


@server.tool(title="Server info", annotations=READ_ONLY)
@guarded
def info() -> dict[str, Any]:
    """Health check: the server version, its limits and the date it uses for 'present'. Call it first when a task begins or when another tool of this server fails."""
    return {"name": "career-architect", "version": SERVER_VERSION, "today": dt.datetime.now(dt.timezone.utc).date().isoformat(),
            "limits": {"document_chars": MAX_DOC, "documents": MAX_DOCS, "total_chars": MAX_TOTAL}, "stateless": True}


@server.tool(title="Read the Jobs guide", annotations=READ_ONLY)
@guarded
def guide(topic: Annotated[str, Field(description="`start` (default) for the main instructions, or the path of a document the instructions name, for example `workflows/score.md`, `workflows/resume.md`, `references/storage.md`, `references/reactive-resume.md`, `style/voice.md`, `assets/profile.md`. The `.md` is optional.")] = "start") -> dict[str, Any]:
    """Use FIRST, at the start of any task about a job posting, resume, cover letter, application, interview or the person's career records, and again whenever the instructions tell you to read
    another document. Returns the current instructions of the `jobs` skill: the rules that keep every claim traceable to the person's confirmed facts, which tool to call for what, and the
    storage protocol for their Google Drive. Follow it. It is served live, so it is always the current version. `topic` picks a document; the answer lists every available topic."""
    key = guide_key(topic)
    if key is None:
        raise ToolError(f"no guide document named {str(topic)[:80]!r}. Available: {', '.join(sorted(GUIDE))}")
    return {"topic": key, "text": GUIDE[key], "skill_version": GUIDE_VERSION, "topics": sorted(GUIDE)}


@server.tool(title="Clean text read from Drive", annotations=READ_ONLY)
@guarded
def normalize_text(text: Doc, source: Annotated[str, Field(description="docs (text from Google Docs get_document), auto (default: recognises each source by its marks), drive_read, base64 or plain")] = "auto") -> dict[str, Any]:
    """Get clean, editable text from a document you read: removes the section-break line Google Docs puts first and undoes the escaping, doubled blank lines or base64 of other Drive readers. Use it before you edit a document's text yourself; the other tools clean their document arguments on their own."""
    if not isinstance(text, str) or len(text) > MAX_DOC:
        raise ToolError(f"text must be at most {MAX_DOC:,} characters")
    try:
        return {"text": career.normalize_drive_text(text, source)}
    except ValueError as e:
        raise ToolError(str(e))


@server.tool(title="Build the skills index", annotations=READ_ONLY)
@guarded
def build_index(
    facts_docs: Annotated[list[str], Field(description="Every facts fragment: the shared one (aliases, credentials, education) and one per role. All of them, so years and tags are complete.")],
    today: Annotated[str | None, Field(description="YYYY-MM-DD; only for tests")] = None,
) -> dict[str, Any]:
    """Use after any change to the person's facts, and to validate them before saving. Validates every facts fragment together and generates the `skills` index: each skill's years
    (union of role spans), last use, depth, evidence atoms, aliases, unconfirmed atoms, which role holds which atom, and the career length. Save the returned `skills_md` as the `skills`
    document; scoring and linting need only that. Returns errors instead when the facts are invalid: fix them before saving anything."""
    docs = _docs("facts_docs", facts_docs)
    facts = _facts("facts_docs", docs)
    when = _today(today)
    errors = career.validate(facts, when)
    if errors:
        return {"ok": False, "errors": errors}
    idx = career.build_index(facts, when)
    return {"ok": True, "skills_md": career.render_skills_md(facts, when), "tags": len(idx),
            "roles": len(facts["roles"]), "atoms": sum(len(r.get("atoms") or []) for r in facts["roles"])}


@server.tool(title="Score a posting", annotations=READ_ONLY)
@guarded
def match(
    skills_md: Doc,
    profile_md: Doc,
    requirements: Annotated[str, Field(description="tag[:must|nice[:min_years]],... e.g. okta:must:5,terraform:nice. Use the tag names in skills_md; aliases resolve.")],
) -> dict[str, Any]:
    """Use to score how well a job posting fits the person, before any resume or letter. Coverage table and score ceiling for a list of the posting's requirements, from the skills index
    and the profile's never_claim / known_gaps. The final score is the ceiling or one point below with a stated reason, never above. Lists requirements the person has not been asked about (`ask`)."""
    parsed = _index(_text("skills_md", skills_md))
    profile = _profile(_text("profile_md", profile_md))
    reqs = _text("requirements", requirements)
    if not career.parse_reqs(reqs):
        raise ToolError("requirements is empty")
    rows, strict, lenient, table = career.match_table(parsed["idx"], parsed["amap"], profile, parsed["pending"], reqs)
    return {"table": table, "ceiling": strict, "ceiling_if_every_unasked_is_met": lenient,
            "rows": [{"requirement": r["tag"], "level": r["lvl"], "status": r["status"], "years": r["yrs"], "depth": r["depth"], "evidence": r["ev"]} for r in rows],
            "ask": [r["tag"] for r in rows if r["status"] == "unasked"]}


@server.tool(title="Lint a resume selection", annotations=READ_ONLY)
@guarded
def lint_resume(
    selection_yaml: Doc,
    skills_md: Doc,
    profile_md: Doc,
    facts_docs: Annotated[list[str], Field(description="The facts fragments that hold the roles and atoms the selection cites, plus the shared fragment. Not the whole career.")],
    today: Annotated[str | None, Field(description="YYYY-MM-DD; only for tests")] = None,
) -> dict[str, Any]:
    """Use to check a tailored resume selection before it is written anywhere: every bullet traces to a usable atom, no invented numbers or scope, never_claim respected, skills exist in the
    index, years match the computed career, plus style warnings. Returns the issues and the plain-text resume for a read-through. Fix every error (E) before continuing."""
    parsed = _index(_text("skills_md", skills_md))
    profile = _profile(_text("profile_md", profile_md))
    facts = _facts("facts_docs", _docs("facts_docs", facts_docs))
    facts["aliases"] = {**parsed["aliases"], **facts.get("aliases", {})}
    when = _today(today)
    sel = _yaml("selection_yaml", _text("selection_yaml", selection_yaml))
    if not isinstance(sel, dict):
        raise ToolError("selection_yaml must be a YAML mapping (target, summary, skills, roles)")
    ctx = career.Ctx.from_data(facts, profile, when)
    issues = _issues(career.lint(ctx, sel, idx=parsed["idx"], career_months=parsed["career_months"]))
    out = _report(issues)
    try:
        out["resume_text"] = career.render_text(ctx, sel)
    except KeyError as e:
        out["resume_text"] = ""
        out["issues"].append({"level": "E", "where": "roles", "message": f"role {e} is not in the facts you supplied"})
        out.update(ok=False, errors=out["errors"] + 1)
    return out


@server.tool(title="Lint a cover letter", annotations=READ_ONLY)
@guarded
def lint_cover(
    cover_yaml: Doc,
    skills_md: Doc,
    profile_md: Doc,
    facts_docs: Annotated[list[str], Field(description="The facts fragments that hold the atoms the letter cites, plus the shared fragment.")],
    posting_text: Annotated[str, Field(description="The job posting text, so statements about the company can be checked.")] = "",
    today: Annotated[str | None, Field(description="YYYY-MM-DD; only for tests")] = None,
) -> dict[str, Any]:
    """Use to check a cover letter before it is saved: claims about the person cite atoms, statements about the company come from the posting, no invented figures, voice rules.
    Returns the issues, the plain text, and the HTML (`content_html`, `recipient_html`, `name`) to save as a Reactive Resume cover letter."""
    parsed = _index(_text("skills_md", skills_md))
    profile = _profile(_text("profile_md", profile_md))
    facts = _facts("facts_docs", _docs("facts_docs", facts_docs))
    facts["aliases"] = {**parsed["aliases"], **facts.get("aliases", {})}
    when = _today(today)
    letter = _yaml("cover_yaml", _text("cover_yaml", cover_yaml))
    if not isinstance(letter, dict):
        raise ToolError("cover_yaml must be a YAML mapping (target, recipient, paragraphs)")
    jd = _text("posting_text", posting_text, required=False)
    ctx = career.Ctx.from_data(facts, profile, when)
    issues = _issues(career.lint_letter(ctx, letter, None, idx=parsed["idx"], career_months=parsed["career_months"], jd=jd))
    out = _report(issues)
    recipient, content = career.letter_html(ctx, letter)
    out.update(cover_text=career.letter_text(ctx, letter), recipient_html=recipient, content_html=content,
               name=career.doc_title(ctx, letter.get("target") or {}, "Cover Letter")[:100])
    return out


def fit_name(company: str, role: str, who: str, kind: str, limit: int = 64) -> str:
    """'Company - Role - Person Kind' that fits Reactive Resume's MCP name limit (64 characters for resumes). The role gives way first:
    it is the longest part and the company and person are what a recruiter searches for."""
    tail = f"{who} {kind}".strip()
    full = " - ".join(p for p in (company, role, tail) if p)
    if len(full) <= limit:
        return full
    room = limit - len(f"{company} - ") - len(f" - {who}")
    if room >= 10:
        return f"{company} - {role[:room].rstrip(' -,&')} - {who}"
    return full[:limit].rstrip()


# Item shapes of Reactive Resume 5.x, used when the caller does not pass the Master's own items. Field names come from the live schema.
DEFAULT_MASTER = {"data": {"summary": {"title": "Summary", "content": ""}, "sections": {
    "experience": {"items": [{"id": "x", "hidden": False, "company": "", "position": "", "location": "", "period": "",
                              "website": {"url": "", "label": "", "inlineLink": False}, "description": "", "roles": []}]},
    "skills": {"items": [{"id": "y", "hidden": False, "icon": "", "iconColor": "", "name": "", "proficiency": "", "level": 0, "keywords": []}]},
    "education": {"hidden": False, "items": []}, "certifications": {"hidden": False, "items": []}, "profiles": {"hidden": False, "items": []}}}}


@server.tool(title="Build the Reactive Resume patch", annotations=READ_ONLY)
@guarded
def resume_patch(
    selection_yaml: Doc,
    skills_md: Doc,
    profile_md: Doc,
    facts_docs: Annotated[list[str], Field(description="Fragments holding the cited roles and atoms AND the shared fragment (credentials and education are printed on the resume).")],
    master_json: Annotated[str, Field(description="Optional: JSON of the Master resume (or just data.sections.experience/skills first items and data.summary) so item fields match the instance exactly. Omit to use Reactive Resume 5.x defaults.")] = "",
    today: Annotated[str | None, Field(description="YYYY-MM-DD; only for tests")] = None,
) -> dict[str, Any]:
    """Use to turn a checked resume selection into the edit to make in Reactive Resume. Lints the selection and, only when it has no errors, returns the JSON Patch `operations` that fill a duplicate
    of the person's Master resume (summary, experience, skills, header, education, certifications), plus `resume_name` (at most 64 characters) and `resume_slug` for the duplicate. Apply the operations
    unchanged with Reactive Resume's apply_resume_patch."""
    linted = lint_resume(selection_yaml, skills_md, profile_md, facts_docs, today)
    if not linted["ok"]:
        return {"ok": False, "errors": linted["errors"], "issues": linted["issues"], "operations": []}
    parsed = _index(_text("skills_md", skills_md))
    profile = _profile(_text("profile_md", profile_md))
    facts = _facts("facts_docs", _docs("facts_docs", facts_docs))
    facts["aliases"] = {**parsed["aliases"], **facts.get("aliases", {})}
    sel = _yaml("selection_yaml", _text("selection_yaml", selection_yaml))
    master = DEFAULT_MASTER
    if master_json.strip():
        try:
            master = json.loads(master_json)
            master["data"]["sections"]["experience"], master["data"]["sections"]["skills"]
        except (ValueError, KeyError, TypeError):
            raise ToolError("master_json must be the Master resume JSON: an object with data.sections.experience and data.sections.skills")
    ctx = career.Ctx.from_data(facts, profile, _today(today))
    ops = career.content_ops(ctx, sel, master)
    target = sel.get("target") or {}
    return {"ok": True, "warnings": linted["warnings"], "issues": linted["issues"], "operations": ops,
            "resume_name": fit_name(target.get("company", ""), target.get("role", ""), str(profile.get("name") or ""), "Resume"),
            "resume_name_full": career.doc_title(ctx, target),
            "resume_slug": career.slugify(f"{target.get('company', '')} - {target.get('role', '')}"),
            "resume_text": linted["resume_text"]}


# ---------------------------------------------------------------- public postings

POSTING_HOSTS = {"api.ashbyhq.com", "boards-api.greenhouse.io", "api.lever.co"}
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_./?&=,%:-]+$")


def _fetch_json(url: str) -> Any:
    """Fetch one of the three public ATS APIs. Only those hosts, only https, bounded in time and size."""
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or u.netloc not in POSTING_HOSTS or not _SAFE_PATH.match(u.path + ("?" + u.query if u.query else "")) or ".." in u.path:
        raise ToolError("refusing to fetch that address")
    req = urllib.request.Request(url, headers={"User-Agent": career.USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read(3_000_000)
    return json.loads(body)


@server.tool(title="Read a public job posting", annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
@guarded
def posting(url: Annotated[str, Field(description="A public Ashby, Greenhouse or Lever posting URL.")]) -> dict[str, Any]:
    """Use when the person gives an Ashby, Greenhouse or Lever posting link: reads pay range, reports-to line, posting date and description from the ATS's public API (which shows pay ranges the
    rendered page hides). `pay` is empty when the posting states none. Contacts only those ATS API hosts; other sites must be pasted or fetched some other way."""
    if len(url) > 500 or not url.lower().startswith(("https://", "http://")):
        raise ToolError("url must be an http(s) address of a posting")
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            result = career.parse_posting(url, fetch=_fetch_json)
    except SystemExit:
        raise ToolError((err.getvalue().replace("error:", "").strip() or "unsupported posting URL") + "")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ToolError(f"could not read that posting: {getattr(e, 'reason', e)}")
    if not result["title"]:
        raise ToolError("that posting id is not on the board any more (closed or renumbered)")
    result["text"] = result["text"][:20000]
    return result


# ---------------------------------------------------------------- HTTP app

@server.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": SERVER_VERSION})


class TokenGate:
    """Refuse every request except /healthz that does not carry the shared secret. Compared in constant time."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/healthz":
            got = b""
            for key, value in scope["headers"]:
                if key == b"x-career-token":
                    got = value.strip()
                elif key == b"authorization" and value[:7].lower() == b"bearer ":
                    got = value[7:].strip()
            if not hmac.compare_digest(got, self.token):
                # Enough to tell a caller that sent no token (a gateway that dropped the header) from one that sent a wrong one. Never the value.
                log.warning("unauthorized request to %s: token header %s", scope["path"], "missing" if not got else "present but wrong")
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app(token: str | None = None):
    app = server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True, max_request_body_size=MAX_BODY,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts, allowed_origins=[]),
    )
    return TokenGate(app, token) if token else app


def main() -> None:
    import uvicorn
    logging.getLogger().setLevel(LOG_LEVEL)
    token = os.environ.get("CAREER_MCP_TOKEN", "").strip() or None
    if not token:
        if os.environ.get("CAREER_MCP_ALLOW_UNSECURED") != "1":
            sys.exit("CAREER_MCP_TOKEN is not set. Refusing to start: without it anyone who can reach this port can call the tools. "
                     "Set it (openssl rand -hex 32), or set CAREER_MCP_ALLOW_UNSECURED=1 for local development only.")
        print("warning: running WITHOUT authentication (CAREER_MCP_ALLOW_UNSECURED=1)", file=sys.stderr)
    uvicorn.run(build_app(token), host=os.environ.get("MCP_HOST", "0.0.0.0"), port=int(os.environ.get("MCP_PORT", "8080")),
                log_level="warning", access_log=False, server_header=False)


if __name__ == "__main__":
    main()
