#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml"]
# ///
"""Deterministic helpers for the jobs skill.

Everything that does not need judgment lives here so the model spends tokens
only on requirement extraction and bullet wording:

  init         copy the profile/facts templates into the data folder
  skills       validate facts.md and regenerate skills.md (years = union of role spans)
  match        coverage table + score ceiling for a list of job requirements
  select       ranked candidate atoms per role for a list of tags
  build        lint a selection.yml and render resume.md for review
  patch        lint a selection.yml and, if clean, print the Reactive Resume JSON Patch operations
               (apply them with the Reactive Resume MCP server's apply_resume_patch)
  cover-patch  lint cover.yml and, if clean, print the HTML for a Reactive Resume saved cover letter
               (create or update it with the Reactive Resume MCP server's create_cover_letter/update_cover_letter)
  posting      read a public Ashby/Greenhouse/Lever posting: pay range, reports-to, description
  check        confirm the data folder and profile.md are set up (no network)

This script never talks to Reactive Resume itself: it only produces the JSON Patch operations and HTML that go into
its MCP tools, which the assistant calls directly once the Reactive Resume MCP server is connected (see
`references/local-mode.md` for how to connect it, and `references/reactive-resume.md` for which tools to use).
Resumes, PDFs, saved cover letters and the application tracker all live in Reactive Resume; nothing here stores a
Reactive Resume address or API key.

Data folder: --data, $CAREER_DATA, or the default below.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import html
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import yaml

DEFAULT_ROOT = Path.home() / "Documents/Career Architect"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
# ATS APIs answer Python's default urllib User-Agent with a block on some hosts; name ourselves.
USER_AGENT = "career-architect/3"

DEPTH = {"exposure": 0, "used": 1, "owned": 2, "designed": 3}
STATUS = {"verified", "needs_number", "unconfirmed", "excluded"}
USABLE = {"verified", "needs_number"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- loading

class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses YAML aliases. The hosted service parses text written by other people, and a chain of
    aliases ("billion laughs") expands to gigabytes; nothing in a facts or profile document needs one."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.events.AliasEvent):
            raise yaml.YAMLError("YAML aliases (&anchor and *alias) are not allowed in career documents")
        return super().compose_node(parent, index)


def load_yaml(text: str):
    return yaml.load(text, Loader=_StrictLoader)


def parse_block(text: str) -> dict:
    """Parse the first ```yaml fence of a markdown document (or the whole text)."""
    m = re.search(r"```ya?ml\n(.*?)```", text, re.S)
    return load_yaml(m.group(1) if m else text) or {}


def parse_front(text: str) -> dict:
    """Parse the YAML front matter of a markdown document."""
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return (load_yaml(m.group(1)) if m else {}) or {}


def read_block(path: Path) -> dict:
    return parse_block(path.read_text())


def read_front(path: Path) -> dict:
    return parse_front(path.read_text())


# ---------------------------------------------------------------- documents stored in Google Drive

# Where the text comes from decides what was done to it, so `source` names the reader:
#   docs        `get_document` of the Google Docs server: markdown converted from the document body. Nothing is escaped, but the
#               body always opens with a section break, which the converter renders as a leading "---" line.
#   drive_read  a Drive connector that converts a Doc itself (Claude's own `read_file_content`): every line followed by a blank
#               line, a blank line as two spaces, markdown punctuation backslash-escaped.
#   base64      a Drive export, base64 encoded, with a byte order mark and CRLF line ends.
#   plain       already clean.
# `auto` recognises each by its own marks and otherwise leaves the text alone: guessing wrong would change the person's facts.
_MD_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|<])")
_DOCS_BREAK = re.compile(r"[ \t]*---[ \t]*(?:\n|\Z)")


def _looks_doubled(t: str) -> bool:
    """The shape of `drive_read` output. The shape alone (a blank line after every line) also describes ordinary prose whose
    paragraphs are separated by blank lines, so it counts only with one of the connector's own marks: a blank original line
    written as two spaces, or backslash-escaped punctuation."""
    lines = t.replace("\r\n", "\n").split("\n")
    if not (len(lines) >= 3 and len(lines) % 2 == 1 and all(x == "" for x in lines[1::2]) and any(x.strip() for x in lines[0::2])):
        return False
    return any(x == "  " for x in lines[0::2]) or bool(_MD_ESCAPED.search(t))


def _drop_docs_break(t: str) -> str:
    """Remove the section-break line the Docs converter puts first (the text may also have lost its leading newline)."""
    m = _DOCS_BREAK.match(t.lstrip("\n"))
    return t.lstrip("\n")[m.end():] if m else t


def normalize_drive_text(text: str, source: str = "auto") -> str:
    """Restore the original text of a document that was stored in Google Drive as a Google Doc, whichever way it was read
    (see the table above). 'auto' picks by each shape's own marks and falls back to plain."""
    if source not in ("auto", "docs", "drive_read", "base64", "plain"):
        raise ValueError("source must be auto, docs, drive_read, base64 or plain")
    t = text

    def decode(s: str) -> str:
        return base64.b64decode("".join(s.split()), validate=True).decode("utf-8")

    if source == "auto":
        squashed = "".join(t.split())
        if t.startswith(("\n---\n", "---\n---\n")):
            source = "docs"                 # a section break followed by the document's own text (which may open with `---`)
        elif len(squashed) >= 16 and len(squashed) % 4 == 0 and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", squashed):
            try:
                t, source = decode(t), "plain"
            except (ValueError, UnicodeDecodeError):
                source = "plain"            # ordinary words that happen to look like base64
        else:
            source = "drive_read" if _looks_doubled(t) else "plain"
    elif source == "base64":
        try:
            t, source = decode(t), "plain"
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError(f"not valid base64 text: {e}")
    t = t.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if source == "docs":
        t = _drop_docs_break(t)
    elif source == "drive_read":
        t = "\n".join("" if piece == "  " else piece for piece in t.split("\n\n"))
        t = _MD_ESCAPED.sub(r"\1", t)
    return t


def merge_facts(docs) -> dict:
    """One facts dict from several fragments: the layout kept in Drive is a shared document (aliases, credentials, education)
    plus one document per role, each a valid slice of the usual facts YAML. Lists are concatenated and alias lists are
    unioned. A role or atom id that occurs twice is reported by `validate`, not silently merged."""
    out: dict = {"aliases": {}, "credentials": [], "education": [], "roles": [], "log": []}
    for doc in docs:
        d = parse_block(doc) if isinstance(doc, str) else (doc or {})
        if not isinstance(d, dict):
            raise ValueError("a facts document must be a YAML mapping (aliases, credentials, education, roles, log)")
        for key, val in d.items():
            if key == "aliases":
                for tag, syns in (val or {}).items():
                    have = out["aliases"].setdefault(tag, [])
                    have += [s for s in (syns or []) if s not in have]
            elif key in ("credentials", "education", "roles", "log"):
                out[key] += val or []
            else:
                out.setdefault(key, val)
    return out


class Ctx:
    def __init__(self, root: str | None, today: dt.date):
        self.root = Path(root or os.environ.get("CAREER_DATA") or DEFAULT_ROOT).expanduser()
        self.today = today
        self._facts = None
        self._profile = None

    @classmethod
    def from_data(cls, facts: dict, profile: dict, today: dt.date) -> "Ctx":
        """A context over documents already in memory (the hosted service). It never touches a file."""
        ctx = cls("/nonexistent/career-data", today)
        ctx._facts, ctx._profile = facts, profile
        return ctx

    @property
    def facts(self) -> dict:
        if self._facts is None:
            p = self.root / "facts.md"
            if not p.exists():
                die(f"{p} not found. Run `career init` first.")
            self._facts = read_block(p)
        return self._facts

    @property
    def profile(self) -> dict:
        if self._profile is None:
            p = self.root / "profile.md"
            self._profile = read_front(p) if p.exists() else {}
        return self._profile

    def job_dir(self, arg: str) -> Path:
        p = Path(arg).expanduser()
        if p.is_file():
            return p.parent
        if p.is_dir():
            return p
        return self.root / "jobs" / arg


# ---------------------------------------------------------------- tags & dates

def norm(s) -> str:
    return re.sub(r"[^a-z0-9+#]+", "-", str(s).lower()).strip("-")


def alias_map(facts: dict) -> dict:
    m = {}
    for canon, syns in (facts.get("aliases") or {}).items():
        m[norm(canon)] = norm(canon)
        for s in syns or []:
            m[norm(s)] = norm(canon)
    return m


def canon(tag, amap: dict) -> str:
    n = norm(tag)
    return amap.get(n, n)


def month_index(x: str, today: dt.date) -> int:
    x = str(x).strip().lower()
    if x in ("", "present", "now"):
        return today.year * 12 + today.month - 1
    parts = x.split("-")
    return int(parts[0]) * 12 + (int(parts[1]) - 1 if len(parts) > 1 else 0)


def span_months(span, today: dt.date) -> tuple[int, int]:
    a, _, b = str(span).partition("..")
    start, end = month_index(a, today), month_index(b, today)
    if b.strip().isdigit():  # year-only end means through December
        end += 11
    return start, end


def union_months(intervals) -> int:
    total, cur = 0, None
    for s, e in sorted(intervals):
        if cur and s <= cur[1] + 1:
            cur[1] = max(cur[1], e)
        else:
            if cur:
                total += cur[1] - cur[0] + 1
            cur = [s, e]
    if cur:
        total += cur[1] - cur[0] + 1
    return total


def fmt_month(i: int) -> str:
    return f"{MONTHS[i % 12]} {i // 12}"


def fmt_period(span, today: dt.date) -> str:
    s, e = span_months(span, today)
    ended = str(span).partition("..")[2].strip().lower() not in ("", "present", "now")
    return f"{fmt_month(s)} - {fmt_month(e) if ended else 'Present'}"


def iter_atoms(facts: dict):
    for role in facts.get("roles") or []:
        for a in role.get("atoms") or []:
            yield role, a


# ---------------------------------------------------------------- validation & skills index

def validate(facts: dict, today: dt.date) -> list[str]:
    errs, seen, role_ids = [], set(), set()
    for r in facts.get("roles") or []:
        if r.get("id") in role_ids:
            errs.append(f"role id duplicate: {r.get('id')}")
        role_ids.add(r.get("id"))
        for k in ("id", "title", "org", "span"):
            if not r.get(k):
                errs.append(f"role {r.get('id', '?')}: missing {k}")
        try:
            span_months(r.get("span", ""), today)
        except (ValueError, IndexError):
            errs.append(f"role {r.get('id', '?')}: bad span {r.get('span')!r} (use YYYY-MM..YYYY-MM or ..present)")
        for a in r.get("atoms") or []:
            i = a.get("id")
            if not i or i in seen:
                errs.append(f"atom id missing or duplicate: {i}")
            seen.add(i)
            if not a.get("say"):
                errs.append(f"{i}: missing say")
            if not a.get("tags"):
                errs.append(f"{i}: no tags")
            if a.get("status", "unconfirmed") not in STATUS:
                errs.append(f"{i}: status must be one of {sorted(STATUS)}")
            if a.get("depth", "used") not in DEPTH:
                errs.append(f"{i}: depth must be one of {list(DEPTH)}")
    return errs


def build_index(facts: dict, today: dt.date) -> dict:
    amap = alias_map(facts)
    idx: dict = {}
    for role, a in iter_atoms(facts):
        if a.get("status", "unconfirmed") not in USABLE:
            continue
        span = span_months(a.get("span") or role["span"], today)
        for t in a.get("tags") or []:
            e = idx.setdefault(canon(t, amap), {"iv": [], "depth": 0, "atoms": [], "end": 0, "cred": False})
            if DEPTH.get(a.get("depth", "used"), 1) > 0 and not a.get("no_years"):  # exposure (a POC) or an undated claim is not years of experience
                e["iv"].append(span)
            e["depth"] = max(e["depth"], DEPTH.get(a.get("depth", "used"), 1))
            e["atoms"].append(a["id"])
            e["end"] = max(e["end"], span[1])
    now = today.year * 12 + today.month - 1
    for e in idx.values():
        e["years"] = round(union_months(e["iv"]) / 12, 1)
        e["last"] = "present" if e["end"] >= now else f"{e['end'] // 12}-{e['end'] % 12 + 1:02d}"
    for c in (facts.get("credentials") or []) + (facts.get("education") or []):
        for t in c.get("tags") or []:
            e = idx.setdefault(canon(t, amap), {"iv": [], "depth": 0, "atoms": [], "end": 0, "years": 0.0, "last": str(c.get("year", "")), "cred": True})
            e["cred"] = True
    return idx


DEPTH_NAME = {v: k for k, v in DEPTH.items()}


def pending_from_facts(facts: dict, amap: dict) -> dict:
    """Tags of atoms the person has not confirmed, each with the atom that carries it: the exact question `match` should ask."""
    pending: dict = {}
    for _, a in iter_atoms(facts):
        if a.get("status", "unconfirmed") not in USABLE:
            for t in a.get("tags") or []:
                pending.setdefault(canon(t, amap), []).append(f"{a['id']} ({a.get('status', 'unconfirmed')})")
    return pending


def render_skills_md(facts: dict, today: dt.date) -> str:
    """skills.md holds everything scoring and linting need, so neither has to read the facts (54 KB for a 12-year career):
    the tag table with a few evidence atom ids per tag, credentials, aliases, unconfirmed atoms, and the career length in months."""
    idx = build_index(facts, today)
    rows = sorted(idx.items(), key=lambda kv: (-kv[1]["years"], kv[0]))
    out = [f"<!-- GENERATED by career.py skills on {today}. Do not edit; edit the facts. -->",
           "# Skills index", "tag|yrs|last|depth|atoms|evidence", "-|-|-|-|-|-"]
    for tag, e in rows:
        depth = "cert" if e["cred"] and not e["atoms"] else DEPTH_NAME[e["depth"]]
        out.append(f"{tag}|{e['years']:g}|{e['last']}|{depth}|{len(e['atoms'])}|{'+'.join(e['atoms'][:3])}")
    creds = facts.get("credentials") or []
    if creds:
        out += ["", "# Credentials"] + [f"- {c.get('name')} ({c.get('issuer', '')}, {c.get('year', '')})" for c in creds]
    aliases = {k: v for k, v in (facts.get("aliases") or {}).items() if v}
    if aliases:
        out += ["", "# Aliases"] + [f"{k}: {', '.join(str(s) for s in v)}" for k, v in aliases.items()]
    pending = pending_from_facts(facts, alias_map(facts))
    if pending:
        out += ["", "# Pending"] + [f"{t}: {'; '.join(v)}" for t, v in sorted(pending.items())]
    roles = facts.get("roles") or []
    if roles:
        # Which fragment holds which atom: the agent opens `facts - <role id>` for the roles it needs and never the whole career.
        out += ["", "# Roles", "id|title|org|span|atoms", "-|-|-|-|-"]
        out += [f"{r['id']}|{r.get('title', '')}|{r.get('org', '')}|{r.get('span', '')}|{' '.join(str(a['id']) for a in r.get('atoms') or [])}" for r in roles]
    months = union_months([span_months(r["span"], today) for r in roles])
    out += ["", "# Career", f"career_months: {months}"]
    return "\n".join(out) + "\n"


def parse_skills_md(text: str) -> dict:
    """The inverse of render_skills_md, for callers that hold only the index: the hosted service scores and lints from it
    without ever receiving the facts. Older indexes (no evidence column, no aliases) still parse."""
    idx: dict = {}
    aliases: dict = {}
    pending: dict = {}
    roles: list = []
    months = None
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            section = line[2:].strip().lower()
            continue
        if not line or line.startswith("<!--"):
            continue
        if section == "skills index":
            if line.startswith(("tag|", "-|")):
                continue
            f = line.split("|")
            if len(f) < 5:
                continue
            tag, depth = f[0], f[3]
            evidence = [x for x in (f[5].split("+") if len(f) > 5 else []) if x]
            count = int(f[4])
            if depth != "cert" and count and not evidence:        # written before the evidence column existed
                evidence = ["(atom)"] * min(count, 3)
            idx[tag] = {"iv": [], "depth": DEPTH.get(depth, 0), "atoms": evidence, "end": 0,
                        "years": float(f[1]), "last": f[2], "cred": depth == "cert"}
        elif section in ("aliases", "pending"):
            key, _, val = line.partition(":")
            if section == "aliases":
                aliases[key.strip()] = [s.strip() for s in val.split(",") if s.strip()]
            else:
                pending[key.strip()] = [s.strip() for s in val.split(";") if s.strip()]
        elif section == "roles":
            f = line.split("|")
            if len(f) >= 5 and not f[0].startswith("-") and f[0] != "id":
                roles.append({"id": f[0], "title": f[1], "org": f[2], "span": f[3], "atoms": f[4].split()})
        elif section == "career" and line.startswith("career_months:"):
            months = int(line.partition(":")[2])
    return {"idx": idx, "aliases": aliases, "amap": alias_map({"aliases": aliases}), "pending": pending, "career_months": months, "roles": roles}


def cmd_skills(ctx: Ctx, args):
    errs = validate(ctx.facts, ctx.today)
    if errs:
        print("facts.md problems:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    (ctx.root / "skills.md").write_text(render_skills_md(ctx.facts, ctx.today))
    print(f"skills.md: {len(build_index(ctx.facts, ctx.today))} tags, {sum(len(list(r.get('atoms') or [])) for r in ctx.facts.get('roles') or [])} atoms")
    return 0


# ---------------------------------------------------------------- match / select

def parse_reqs(s: str):
    out = []
    for part in s.split(","):
        bits = [b.strip() for b in part.split(":")]
        if not bits[0]:
            continue
        lvl = "must"
        if len(bits) > 1 and bits[1]:
            lvl = {"m": "must", "must": "must", "n": "nice", "nice": "nice"}.get(bits[1].lower(), "must")
        yrs = float(bits[2]) if len(bits) > 2 and bits[2] else None
        out.append((bits[0], lvl, yrs))
    return out


def req_status(tag, minyrs, idx, amap, never, gaps, pending=None):
    c = canon(tag, amap)
    if c in never:
        return "gap", "-", "-", "never_claim"
    e = idx.get(c)
    if e:
        ev = ",".join(e["atoms"][:3]) or "credential"
        if not e["atoms"]:
            return "met", "-", "cert", ev
        depth = DEPTH_NAME[e["depth"]]
        if e["depth"] == 0:
            return "partial", f"{e['years']:g}", depth, ev
        if minyrs and e["years"] < minyrs:
            st = "partial" if e["years"] >= 0.8 * minyrs else "short"
            return st, f"{e['years']:g}", depth, f"{ev} (needs {minyrs:g})"
        return "met", f"{e['years']:g}", depth, ev
    if c in gaps:
        return "gap", "-", "-", "known gap"
    if pending and c in pending:
        return "unasked", "-", "-", f"unverified: {'; '.join(pending[c][:2])}. Ask the candidate to confirm"
    return "unasked", "-", "-", "not in facts or known_gaps: ask the candidate"


def ceiling(rows, unasked_as: str) -> int:
    """Rule-based score cap; keeps the rubric semantics (1-10, strict)."""
    def st(r):
        return unasked_as if r["status"] == "unasked" else r["status"]
    musts = [r for r in rows if r["lvl"] == "must"]
    nices = [r for r in rows if r["lvl"] == "nice"]
    gap = sum(1 for r in musts if st(r) == "gap")
    short = sum(1 for r in musts if st(r) == "short")
    part = sum(1 for r in musts if st(r) == "partial")
    if musts and gap / len(musts) > 0.5:
        return 2
    if short >= 1 or gap >= 2:
        return 4
    if gap == 1:
        return 6
    nice_missing = sum(1 for r in nices if st(r) != "met")
    if part:
        return 8 if part + nice_missing <= 2 else 7
    return {0: 10, 1: 9, 2: 8}.get(nice_missing, 7)


def note_if_empty(ctx: Ctx):
    if not ctx.facts.get("roles"):
        print("note: facts.md has no roles yet, so nothing can be scored or selected. Run the intake workflow first (workflows/intake.md).", file=sys.stderr)


def match_table(idx: dict, amap: dict, profile: dict, pending: dict, req: str):
    """Score a requirement list against a skills index: (rows, strict ceiling, lenient ceiling, printable table).
    Shared by the CLI (index built from facts.md) and the hosted service (index parsed from skills.md)."""
    never = {canon(x, amap) for x in profile.get("never_claim") or []}
    gaps = {canon(x, amap) for x in profile.get("known_gaps") or []}
    pending = {k: list(v) for k, v in pending.items()}
    for tag, note in (profile.get("pending") or {}).items():  # things the person said but has not yet tied to a job
        pending.setdefault(canon(tag, amap), []).append(str(note).rstrip(". "))
    rows = []
    for tag, lvl, yrs in parse_reqs(req):
        st, y, d, ev = req_status(tag, yrs, idx, amap, never, gaps, pending)
        rows.append({"tag": tag, "lvl": lvl, "status": st, "yrs": y, "depth": d, "ev": ev})
    strict, lenient = ceiling(rows, "gap"), ceiling(rows, "met")
    line = f"ceiling: {strict}"
    if strict != lenient:
        line += f" (up to {lenient} if every 'unasked' turns out to be met)"
    lines = ["req|lvl|status|yrs|depth|evidence"]
    lines += [f"{r['tag']}|{r['lvl']}|{r['status']}|{r['yrs']}|{r['depth']}|{r['ev']}" for r in rows]
    lines.append(line + "  -> final score is the ceiling or one point below, with a stated reason")
    return rows, strict, lenient, "\n".join(lines)


def cmd_match(ctx: Ctx, args):
    note_if_empty(ctx)
    amap = alias_map(ctx.facts)
    _, _, _, table = match_table(build_index(ctx.facts, ctx.today), amap, ctx.profile, pending_from_facts(ctx.facts, amap), args.req)
    print(table)
    return 0


def recency_key(role, today):
    return -span_months(role["span"], today)[1]


def cmd_select(ctx: Ctx, args):
    note_if_empty(ctx)
    amap = alias_map(ctx.facts)
    want = {canon(t, amap) for t, _, _ in parse_reqs(args.tags)}
    roles = sorted(ctx.facts.get("roles") or [], key=lambda r: recency_key(r, ctx.today))
    for n, role in enumerate(roles):
        cap = args.cap or (6 if n < 2 else 3)
        scored = []
        for a in role.get("atoms") or []:
            if a.get("status", "unconfirmed") not in USABLE:
                continue
            only = {canon(t, amap) for t in a.get("only_for") or []}
            if only and not only & want:  # conditional atom (e.g. salon wording): only when the posting fits
                continue
            overlap = len({canon(t, amap) for t in a.get("tags") or []} & want)
            scored.append((overlap, DEPTH.get(a.get("depth", "used"), 1), a))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        keep = [s for s in scored if s[0] > 0][:cap]
        if not keep and n < 2:  # recent roles should not come out blank
            keep = scored[:2]
        print(f"## {role['id']} | {role['title']} | {role['org']} | {role['span']}")
        if role.get("context"):
            print(f"   context: {role['context']}")
        if not keep:
            print("   (no tag overlap: omit or compress this role)")
        for ov, _, a in keep:
            mark = " [no figure]" if a.get("status") == "needs_number" else ""
            note = f"  // {a['note']}" if a.get("note") else ""
            print(f"- {a['id']} [{a.get('depth', 'used')}, {ov} match]{mark} {a['say']}{note}")
    return 0


# ---------------------------------------------------------------- lint / build

BANNED = [r"\bspearhead\w*", r"\bleverag(?:e|ed|es|ing)\b", r"\borchestrat\w*", r"\butiliz\w*",
          r"\brobust\b", r"\bseamless(?:ly)?\b", r"\bcutting[- ]edge\b", r"\bproven track record\b",
          r"\bresults[- ]driven\b", r"\bpassionate\b", r"\bsynerg\w*", r"\bdynamic\b",
          r"\bdetail[- ]oriented\b", r"\bresponsible for\b", r"\bworked on\b", r"\bseasoned\b",
          r"\bholistic\b", r"\bpivotal\b", r"\bfoster\w*", r"\bdelve\w*", r"\bmeticulous\w*",
          r"\btestament\b", r"\bunderscor\w*", r"\bshowcas\w*", r"\bensur(?:e|ed|es|ing)\b",
          r"\bin today's\b", r"\bfast-paced\b"]
TAIL = re.compile(r",\s+(?:enabling|ensuring|resulting in|driving|allowing|improving|reducing|increasing|"
                  r"leading to|making|helping|providing|delivering)\b", re.I)
NUM = re.compile(r"(?<![A-Za-z0-9.])(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB](?![a-z]))?")
YEARS = re.compile(r"(\d+(?:\.\d+)?)\+?[\s-]*(?:years?|yrs?)\b", re.I)
TERM = re.compile(r"\b[A-Z][A-Za-z0-9+#]*[A-Za-z0-9+#]\b")
STOP_TERMS = set(MONTHS) | {"i", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "q1", "q2", "q3", "q4"}


STOP_WORDS = set("""a an the and or of to in on at for from with without by as is are was were be been being that this these those it its
into across about over per than then also both each all any not no which who whom whose their there our my your i we you they them he she his her
would will can could should has have had up out off more most very just only""".split())
NUMWORDS = re.compile(r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozens?|hundreds?|thousands?|millions?|half|double[ds]?|triple[ds]?)\b", re.I)

NUMVAL = {w: float(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
NUMVAL["dozen"] = 12.0


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9+#']*", text.lower()) if len(w) >= 3 and w not in STOP_WORDS]


def _stem(w: str) -> str:
    return w if len(w) <= 5 else w[:5]  # crude but enough to treat reconcile/reconciles/reconciliation as one word


def novel_words(text: str, vocab: str) -> list[str]:
    """Content words in `text` that the source atom(s) never used: the fingerprint of an embellished claim."""
    have = {_stem(w) for w in _words(vocab)}
    out: list[str] = []
    for w in _words(text):
        if _stem(w) not in have and w not in out:
            out.append(w)
    return out


def known_term(word: str, corpus: set) -> bool:
    w = word.lower()
    return w in corpus or w + "s" in corpus or w + "es" in corpus or (w.endswith("s") and w[:-1] in corpus)


def terms(text: str) -> list[str]:
    """Capitalised tool-like words, ignoring the first word of each sentence."""
    out = []
    for m in TERM.finditer(text):
        before = text[:m.start()].rstrip()
        if before and not before.endswith((".", "!", "?")):
            out.append(m.group(0))
    return out


def numbers_in(text: str) -> set:
    out = set()
    for m in NUM.finditer(text):
        v = float(m.group(1).replace(",", ""))
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
        if mult == 1 and 1990 <= v <= 2100:
            continue
        out.add(round(v * mult, 2))
    return out


def corpus_words(facts: dict, profile: dict) -> set:
    blob = json.dumps(facts, default=str) + json.dumps(profile, default=str)
    return set(re.findall(r"[a-z0-9+#]+", blob.lower()))


LETTER_BANNED = [r"\bI am writing to\b", r"\bI am (?:excited|thrilled|delighted|eager|pleased)\b", r"\b(?:excited|thrilled|eager) (?:to|about)\b",
                 r"\bperfect (?:fit|candidate)\b", r"\balign(?:s|ed|ment)? (?:perfectly |closely |well )?with\b",
                 r"\bthank you for (?:your )?(?:time|consideration)\b", r"\bopportunity to (?:contribute|join)\b", r"\bpassion for\b",
                 r"\bI believe (?:I|my)\b", r"\bunique (?:blend|combination|set of)\b", r"\bproven ability\b"]


def prose_issues(texts, never, first_person_ok=False, extra_banned=()):
    """Style and never_claim checks shared by the resume and the cover letter."""
    out = []
    for where, text in texts:
        for rx in never:
            if rx.search(text):
                out.append(("E", where, f"never_claim hit: '{rx.pattern[2:-2]}'"))
        for pat in (*BANNED, *extra_banned):
            m = re.search(pat, text, re.I)
            if m:
                out.append(("W", where, f"banned/AI-tell phrase '{m.group(0)}'"))
        if re.search(r"[—–]| -- ", text):
            out.append(("W", where, "dash used as punctuation; use a comma or period"))
        if TAIL.search(text):
            out.append(("W", where, "trailing '..., enabling/ensuring/resulting in' clause"))
        if not first_person_ok and re.search(r"\b(?:I|my|me)\b", text):
            out.append(("W", where, "first-person pronoun"))
    return out


def year_allowed(ctx: Ctx, roles: dict, idx: dict, career_months: int | None = None):
    """'N years' claims may equal the computed career length or any skill's computed years.
    `career_months` replaces the sum over `roles` when the caller holds only some of the roles (the hosted service)."""
    total = (career_months if career_months is not None else union_months([span_months(r["span"], ctx.today) for r in roles.values()])) / 12
    ok = {float(int(total)), float(round(total))}
    for e in idx.values():
        ok |= {float(int(e["years"])), float(round(e["years"]))}
    return ok, total


def lint(ctx: Ctx, sel: dict, idx: dict | None = None, career_months: int | None = None):
    """Check a resume selection. With no arguments everything is derived from the facts. The hosted service passes the
    index parsed from skills.md and the career length, and supplies only the roles and atoms the selection cites."""
    facts, profile = ctx.facts, ctx.profile
    amap = alias_map(facts)
    corpus = corpus_words(facts, profile)
    if idx is None:
        idx = build_index(facts, ctx.today)
    else:
        corpus |= set(re.findall(r"[a-z0-9+#]+", " ".join(idx).lower()))
    roles = {r["id"]: r for r in facts.get("roles") or []}
    by_id = {a["id"]: (r, a) for r, a in iter_atoms(facts)}
    never = [re.compile(r"\b" + re.escape(str(x)) + r"\b", re.I) for x in profile.get("never_claim") or []]
    issues: list[tuple[str, str, str]] = []

    def add(level, where, msg):
        issues.append((level, where, msg))

    texts: list[tuple[str, str]] = []
    summary = (sel.get("summary") or "").strip()
    if summary:
        texts.append(("summary", summary))
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", summary) if s]
        if len(sentences) > 2:
            add("W", "summary", f"{len(sentences)} sentences; keep to 2")
        if len(summary.split()) > 55:
            add("W", "summary", f"{len(summary.split())} words; keep under 55")
        # a summary may cite only figures found in atoms/context; "N years" must match computed career/skill length
        year_ok, total_years = year_allowed(ctx, roles, idx, career_months)
        ok = set()
        for r in roles.values():
            ok |= numbers_in(r.get("context", ""))
        for _, a in by_id.values():
            ok |= numbers_in(a.get("say", ""))
            for v in (a.get("nums") or {}).values():
                ok |= numbers_in(str(v))
        for n in sorted({float(m.group(1)) for m in YEARS.finditer(summary)} - year_ok):
            add("E", "summary", f"number {n:g} is not supported by facts (career length computes to {total_years:.1f} years)")
        for n in sorted(numbers_in(YEARS.sub(" ", summary)) - ok):
            add("E", "summary", f"number {n:g} is not supported by facts")
        for w in terms(summary):
            if not known_term(w, corpus) and w.lower() not in STOP_TERMS:
                add("W", "summary", f"term '{w}' appears nowhere in facts.md/profile.md")

    all_bullets: list[str] = []
    for role_sel in sel.get("roles") or []:
        rid = role_sel.get("id")
        role = roles.get(rid)
        if not role:
            add("E", f"role {rid}", "not in facts.md")
            continue
        allowed_titles = [role["title"], *(role.get("framings") or [])]
        if role_sel.get("title") and role_sel["title"] not in allowed_titles:
            add("E", rid, f"title '{role_sel['title']}' is not the real title or an allowed framing: {allowed_titles}")
        firsts, counts = [], []
        for i, b in enumerate(role_sel.get("bullets") or [], 1):
            where = f"{rid}#{i}"
            text = (b.get("text") or "").strip()
            ids = b.get("atoms") or ([b["atom"]] if b.get("atom") else [])
            if not ids:
                add("E", where, "no atom id: every bullet must trace to an atom")
            allowed = numbers_in(role.get("context", ""))
            for aid in ids:
                pair = by_id.get(aid)
                if not pair:
                    add("E", where, f"atom {aid} not in facts.md")
                    continue
                arole, atom = pair
                if atom.get("only_for"):
                    add("W", where, f"atom {aid} is conditional (only for {', '.join(map(str, atom['only_for']))}): keep it only if the posting fits")
                if arole["id"] != rid:
                    add("E", where, f"atom {aid} belongs to role {arole['id']}, not {rid}")
                if atom.get("status", "unconfirmed") not in USABLE:
                    add("E", where, f"atom {aid} has status {atom.get('status', 'unconfirmed')}; not usable")
                allowed |= numbers_in(atom.get("say", ""))
                for v in (atom.get("nums") or {}).values():
                    allowed |= numbers_in(str(v))
            for n in sorted(numbers_in(text) - allowed):
                add("E", where, f"number {n:g} is not in the atom(s); if it is true, add it to the atom's say/nums")
            vocab = " ".join([role.get("title", ""), role.get("org", ""), role.get("context", "")] +
                             [f"{a.get('say', '')} {' '.join(map(str, a.get('tags') or []))}" for _, a in (by_id[i] for i in ids if i in by_id)])
            for nw in sorted({m.group(0).lower() for m in NUMWORDS.finditer(text)} - {m.group(0).lower() for m in NUMWORDS.finditer(vocab)}):
                if NUMVAL.get(nw) not in allowed:  # 'twelve' is fine when the atom says 12
                    add("E", where, f"number word '{nw}' is not in the atom(s)")
            extra = novel_words(text, vocab)
            if ids and len(extra) >= 3:
                add("W", where, f"adds wording the atom never used: {', '.join(extra[:6])}. If that is a new claim, put it in the atom first; otherwise cut it")
            for w in terms(text):
                if not known_term(w, corpus) and w.lower() not in STOP_TERMS:
                    add("W", where, f"term '{w}' appears nowhere in facts.md/profile.md")
            n_words = len(text.split())
            if n_words > 35:
                add("W", where, f"{n_words} words; tighten")
            if 0 < n_words < 5:
                add("W", where, "very short bullet")
            firsts.append(text.split()[0].lower() if text else "")
            counts.append(n_words)
            texts.append((where, text))
            all_bullets.append(text)
        dup = {f for f in firsts if f and firsts.count(f) > 1}
        if dup:
            add("W", rid, f"repeated leading word(s): {', '.join(sorted(dup))}")
        if len(counts) >= 4 and statistics.pstdev(counts) < 2.5:
            add("W", rid, "bullets are near-uniform in length; vary the rhythm")

    if len(all_bullets) >= 5 and all(numbers_in(b) for b in all_bullets):
        add("W", "all", "every bullet has a metric; let a few stand without one")
    trip = [b for b in all_bullets if re.search(r"[\w/+.-]+(?: [\w/+.-]+)?, [\w/+.-]+(?: [\w/+.-]+)?,? and [\w/+.-]+", b)]
    if len(trip) >= 3 and len(trip) / len(all_bullets) > 0.4:
        add("W", "all", f"{len(trip)} bullets use an 'A, B, and C' list; vary the structure")

    for group in sel.get("skills") or []:
        for item in group.get("items") or []:
            # "GCP and AWS (general use and troubleshooting)" is two skills with a qualifier; every part must be on file
            base = re.sub(r"\s*\(.*?\)", "", item)
            for part in [x for x in re.split(r"\s+and\s+|,|/", base) if x.strip()]:
                if canon(part, amap) not in idx:
                    where = f" (in '{item}')" if part.strip() != item else ""
                    add("E", f"skills/{group.get('name')}", f"'{part.strip()}'{where} is not in skills.md (verified atoms or credentials)")
        texts.append((f"skills/{group.get('name')}", " ".join(group.get("items") or [])))

    issues += prose_issues(texts, never)
    return issues


def letter_html(ctx: Ctx, letter: dict):
    """RR cover-letter items are HTML: an address block, and a body holding salutation, paragraphs, closing and signature."""
    company = (letter.get("target") or {}).get("company") or ""
    lines = letter.get("recipient") or ["Hiring Manager", company]
    lines = [lines] if isinstance(lines, str) else lines
    today = f"{ctx.today:%B} {ctx.today.day}, {ctx.today.year}"
    # Reactive Resume prints no resume header on a cover letter, so the letter carries its own letterhead
    prof = ctx.profile
    contact = " | ".join(str(x) for x in (prof.get("email"), prof.get("phone")) if x)
    head = [x for x in ((f"<strong>{html.escape(str(prof['name']))}</strong>" if prof.get("name") else ""), html.escape(contact),
                        html.escape(str(prof.get("location") or ""))) if x]
    sender = f"<p>{'<br>'.join(head)}</p>" if head else ""
    recipient = f"{sender}<p>{today}</p><p>" + "<br>".join(html.escape(str(x)) for x in lines if x) + "</p><p></p>"
    parts = [f"<p>{html.escape(letter.get('salutation') or 'Dear Hiring Manager,')}</p>"]
    parts += [f"<p>{html.escape(p['text'].strip())}</p>" for p in letter.get("paragraphs") or []]
    parts.append(f"<p>{html.escape(letter.get('closing') or 'Sincerely,')}<br>{html.escape(ctx.profile.get('name', ''))}</p>")
    return recipient, "".join(parts)


def letter_text(ctx: Ctx, letter: dict) -> str:
    company = (letter.get("target") or {}).get("company") or ""
    lines = letter.get("recipient") or ["Hiring Manager", company]
    lines = [lines] if isinstance(lines, str) else lines
    prof = ctx.profile
    letterhead = [x for x in (prof.get("name"), " | ".join(str(v) for v in (prof.get("email"), prof.get("phone")) if v), prof.get("location")) if x]
    out = (letterhead + [""] if letterhead else []) + [f"{ctx.today:%B} {ctx.today.day}, {ctx.today.year}", ""] + [x for x in lines if x] + ["", letter.get("salutation") or "Dear Hiring Manager,", ""]
    for p in letter.get("paragraphs") or []:
        out += [p["text"].strip(), ""]
    return "\n".join(out + [letter.get("closing") or "Sincerely,", ctx.profile.get("name", "")]) + "\n"


INTENT = re.compile(r"\b(?:would|welcome|hope|glad|happy|look forward|love|talk|discuss|conversation|chat|appl(?:y|ying|ied)|interested)\b", re.I)


def lint_letter(ctx: Ctx, letter: dict, job: Path | None, idx: dict | None = None, career_months: int | None = None, jd: str | None = None):
    """Check a cover letter. `idx`, `career_months` and `jd` let the hosted service supply the parts it holds in memory
    (the skills index, the career length and the posting text) instead of reading the facts and a job folder."""
    facts, profile = ctx.facts, ctx.profile
    extra_vocab = ""
    if idx is None:
        idx = build_index(facts, ctx.today)
    else:
        extra_vocab = " ".join(idx)
    roles = {r["id"]: r for r in facts.get("roles") or []}
    by_id = {a["id"]: (r, a) for r, a in iter_atoms(facts)}
    never = [re.compile(r"\b" + re.escape(str(x)) + r"\b", re.I) for x in profile.get("never_claim") or []]
    if jd is None:
        jd = (job / "jd.md").read_text() if job and (job / "jd.md").exists() else ""
    target = letter.get("target") or {}
    corpus = corpus_words(facts, profile) | set(re.findall(r"[a-z0-9+#]+", (jd + " " + " ".join(map(str, target.values())) + " " + extra_vocab).lower()))
    year_ok, total_years = year_allowed(ctx, roles, idx, career_months)
    jd_nums = numbers_in(YEARS.sub(" ", jd))
    issues: list[tuple[str, str, str]] = []
    if not jd:
        issues.append(("W", "letter", "no jd.md in the job folder: statements about the company cannot be checked"))
    if profile.get("name") in (None, "", "Your Name"):
        issues.append(("W", "letter", "profile.md has no real name: the signature would be blank or a placeholder"))
    paras = letter.get("paragraphs") or []
    texts = [("salutation", letter.get("salutation") or ""), ("closing", letter.get("closing") or "")]
    for i, para in enumerate(paras, 1):
        where, text, ids = f"para {i}", (para.get("text") or "").strip(), para.get("atoms") or []
        texts.append((where, text))
        if not ids and not para.get("jd"):
            issues.append(("E", where, "cites no atoms and is not marked jd: true; every claim about you needs an atom"))
        allowed = set(jd_nums) if para.get("jd") else set()
        for aid in ids:
            pair = by_id.get(aid)
            if not pair:
                issues.append(("E", where, f"atom {aid} not in facts.md"))
                continue
            arole, atom = pair
            if atom.get("status", "unconfirmed") not in USABLE:
                issues.append(("E", where, f"atom {aid} has status {atom.get('status', 'unconfirmed')}; not usable"))
            if atom.get("only_for"):
                issues.append(("W", where, f"atom {aid} is conditional (only for {', '.join(map(str, atom['only_for']))}): keep it only if the posting fits"))
            allowed |= numbers_in(atom.get("say", "")) | numbers_in(arole.get("context", ""))
            for v in (atom.get("nums") or {}).values():
                allowed |= numbers_in(str(v))
        for n in sorted({float(m.group(1)) for m in YEARS.finditer(text)} - year_ok):
            issues.append(("E", where, f"number {n:g} is not supported by facts (career length computes to {total_years:.1f} years)"))
        for n in sorted(numbers_in(YEARS.sub(" ", text)) - allowed):
            issues.append(("E", where, f"number {n:g} is not in the cited atoms" + (" or jd.md" if para.get("jd") else "")))
        if ids and not para.get("jd"):
            cited = [by_id[i] for i in ids if i in by_id]
            vocab = " ".join([f"{a.get('say', '')} {' '.join(map(str, a.get('tags') or []))} {r.get('title', '')} {r.get('org', '')} {r.get('context', '')}" for r, a in cited] + [" ".join(map(str, target.values()))])
            for nw in sorted({m.group(0).lower() for m in NUMWORDS.finditer(text)} - {m.group(0).lower() for m in NUMWORDS.finditer(vocab)}):
                if NUMVAL.get(nw) not in allowed:
                    issues.append(("E", where, f"number word '{nw}' is not in the cited atoms"))
            for sent in re.split(r"(?<=[.!?])\s+", text):
                extra = novel_words(sent, vocab)
                if len(extra) >= 5:
                    issues.append(("W", where, f"a sentence adds wording the cited atoms never used: {', '.join(extra[:6])}. Cut it or put the fact in an atom first"))
        for w in terms(text):
            if not known_term(w, corpus) and w.lower() not in STOP_TERMS:
                issues.append(("W", where, f"term '{w}' appears nowhere in facts.md, profile.md or jd.md"))
        if para.get("jd"):  # a jd-only paragraph may state intent, but any other statement about "I" or "my" is a claim that needs an atom
            for sent in re.split(r"(?<=[.!?])\s+", text):
                if re.search(r"\b(?:I|I'm|I've|my|me)\b", sent) and not INTENT.search(sent):
                    issues.append(("W", where, f"claim about you in a jd-only paragraph: '{sent[:70]}'. Cite an atom, or cut it"))
    words = sum(len(t.split()) for w, t in texts if w.startswith("para"))
    if not 90 <= words <= 320:
        issues.append(("W", "letter", f"{words} words in the body; aim for roughly 150 to 300"))
    if not 3 <= len(paras) <= 4:
        issues.append(("W", "letter", f"{len(paras)} paragraphs; three or four reads best"))
    return issues + prose_issues(texts, never, first_person_ok=True, extra_banned=LETTER_BANNED)


def load_selection(ctx: Ctx, arg: str) -> tuple[Path, dict]:
    p = Path(arg).expanduser()
    p = p if p.is_file() else ctx.job_dir(arg) / "selection.yml"
    if not p.exists():
        die(f"{p} not found")
    return p, yaml.safe_load(p.read_text()) or {}


def render_text(ctx: Ctx, sel: dict) -> str:
    roles = {r["id"]: r for r in ctx.facts.get("roles") or []}
    p = ctx.profile
    out = [f"# {p.get('name', '')}", p.get("headline", ""), "", "## Summary", sel.get("summary", ""), "", "## Skills"]
    out += [f"**{g['name']}:** {', '.join(g.get('items') or [])}" for g in sel.get("skills") or []]
    out += ["", "## Experience"]
    for rs in sel.get("roles") or []:
        r = roles[rs["id"]]
        out += ["", f"### {rs.get('title') or r['title']}, {r['org']} ({fmt_period(r['span'], ctx.today)})"]
        out += [f"- {b['text']}" for b in rs.get("bullets") or []]
    return "\n".join(out) + "\n"


def cmd_build(ctx: Ctx, args):
    path, sel = load_selection(ctx, args.job)
    issues = lint(ctx, sel)
    for lv, where, msg in issues:
        print(f"{lv} {where}: {msg}")
    errors = sum(1 for i in issues if i[0] == "E")
    warns = len(issues) - errors
    (path.parent / "resume.md").write_text(render_text(ctx, sel))
    print(f"{errors} error(s), {warns} warning(s); wrote {path.parent / 'resume.md'}")
    return 1 if errors or (args.strict and warns) else 0


# ---------------------------------------------------------------- Reactive Resume JSON Patch
#
# This script never calls Reactive Resume: it only builds the JSON Patch `operations` and HTML that its MCP server's
# tools (apply_resume_patch, create_cover_letter, update_cover_letter) take as input. The assistant calls those tools
# directly once the Reactive Resume MCP server is connected (references/local-mode.md, references/reactive-resume.md).

def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def doc_title(ctx: Ctx, target: dict, kind: str = "Resume") -> str:
    """'Company - Role - Name Resume': the job title travels with the document so a recruiter, a file search
    and a downloaded file all show which role it was written for."""
    who = str(ctx.profile.get("name") or "").strip()
    return " - ".join(p for p in (target.get("company"), target.get("role"), f"{who} {kind}".strip()) if p)


def fit_name(company: str, role: str, who: str, kind: str, limit: int = 64) -> str:
    """'Company - Role - Person Kind' trimmed to fit Reactive Resume's name limit (64 characters for resumes). The
    role gives way first: it is the longest part, and the company and person are what a search turns up."""
    tail = f"{who} {kind}".strip()
    full = " - ".join(p for p in (company, role, tail) if p)
    if len(full) <= limit:
        return full
    room = limit - len(f"{company} - ") - len(f" - {who}")
    if room >= 10:
        return f"{company} - {role[:room].rstrip(' -,&')} - {who}"
    return full[:limit].rstrip()


def html_list(bullets) -> str:
    return "<ul>" + "".join(f"<li><p>{html.escape(b['text'])}</p></li>" for b in bullets) + "</ul>"


def build_items(ctx: Ctx, sel: dict, master: dict):
    """Experience and skills items shaped like the master's own items, so field names come from the instance."""
    sections = master["data"]["sections"]
    exp_tpl = (sections["experience"]["items"] or [{}])[0]
    skl_tpl = (sections["skills"]["items"] or [{}])[0]
    roles = {r["id"]: r for r in ctx.facts.get("roles") or []}
    exp = []
    for rs in sel.get("roles") or []:
        r = roles[rs["id"]]
        item = copy.deepcopy(exp_tpl)
        item.update({"id": str(uuid.uuid4()), "hidden": False, "company": r["org"], "position": rs.get("title") or r["title"],
                     "location": r.get("location", "Remote" if r.get("remote") else ""),
                     "period": fmt_period(r["span"], ctx.today), "description": html_list(rs.get("bullets") or []),
                     "roles": []})
        item["website"] = {"inlineLink": False, **(exp_tpl.get("website") or {}), "url": "", "label": ""}
        exp.append(item)
    skl = []
    for g in sel.get("skills") or []:
        item = copy.deepcopy(skl_tpl)
        item.update({"id": str(uuid.uuid4()), "hidden": False, "name": g["name"], "keywords": list(g.get("items") or [])})
        item.setdefault("icon", "")
        item.setdefault("iconColor", "")
        item.setdefault("proficiency", "")
        item.setdefault("level", 0)
        skl.append(item)
    return exp, skl


def _site(url: str = "", label: str = "") -> dict:
    return {"url": url, "label": label, "inlineLink": False}


def cert_items(creds: list) -> list:
    """One line per certification, always under its full official name: AI HRIS parsers match whole cert names,
    so 'Okta Certified Administrator, Professional and ...' would lose two of the three."""
    out = []
    for c in creds:
        name, issuer = str(c.get("name", "")), str(c.get("issuer", ""))
        out.append({"id": str(uuid.uuid4()), "hidden": False, "title": name,
                    "issuer": "" if issuer.lower() in name.lower() else issuer,  # "Okta" beside "Okta Certified ..." is a wasted column
                    "date": str(c.get("year", "")), "website": _site(), "description": ""})
    return out


def profile_ops(ctx: Ctx, master: dict) -> list:
    """Contact details, education, certifications and profile links come from profile.md and facts.md,
    so the Master only has to supply the template and design."""
    p, f, ops = ctx.profile, ctx.facts, []
    sections = master["data"].get("sections") or {}
    for k in ("name", "headline", "email", "phone", "location"):
        if p.get(k) and p[k] != "Your Name":
            ops.append({"op": "replace", "path": f"/basics/{k}", "value": str(p[k])})

    def put(name, items):
        if items:
            ops.append({"op": "replace", "path": f"/sections/{name}/items", "value": items})
            if (sections.get(name) or {}).get("hidden"):
                ops.append({"op": "replace", "path": f"/sections/{name}/hidden", "value": False})

    put("education", [{"id": str(uuid.uuid4()), "hidden": False, "school": e.get("school", ""), "degree": e.get("degree", ""),
                       "area": e.get("area", ""), "grade": e.get("grade", ""), "location": e.get("location", ""),
                       "period": str(e.get("period", "")), "website": _site(), "description": ""} for e in f.get("education") or []])
    put("certifications", cert_items(f.get("credentials") or []))
    links = []
    for key, icon in (("linkedin", "linkedin-logo"), ("github", "github-logo")):
        if p.get(key):
            url = str(p[key])
            links.append({"id": str(uuid.uuid4()), "icon": icon, "text": re.sub(r"^https?://(www\.)?", "", url).rstrip("/"), "link": url})
    if links:  # inline header links; the stacked Profiles section would only repeat them
        ops.append({"op": "replace", "path": "/basics/customFields", "value": links})
        ops.append({"op": "replace", "path": "/sections/profiles/items", "value": []})
        ops.append({"op": "replace", "path": "/sections/profiles/hidden", "value": True})
    return ops


def content_ops(ctx: Ctx, sel: dict, master: dict) -> list:
    """Everything a selection puts into a resume: summary, experience, skills, plus header, education and certifications."""
    exp, skl = build_items(ctx, sel, master)
    summary_path = "/summary/content" if isinstance(master["data"].get("summary"), dict) else "/summary"
    ops = [{"op": "replace", "path": summary_path, "value": f"<p>{html.escape(sel.get('summary') or '')}</p>"},
           {"op": "replace", "path": "/sections/experience/items", "value": exp},
           {"op": "replace", "path": "/sections/skills/items", "value": skl}]
    return ops + profile_ops(ctx, master)


DESIGN_KEYS = ("template", "page", "typography", "design", "layout")


def design_ops(master: dict) -> list:
    """Copy the Master's look onto a resume. Only on request, so a per-job template choice is never overwritten."""
    meta = master["data"].get("metadata") or {}
    return [{"op": "replace", "path": f"/metadata/{k}", "value": meta[k]} for k in DESIGN_KEYS if k in meta]


# Item shapes of Reactive Resume 5.x, used when the person has not passed the Master's own items with --master-json.
DEFAULT_MASTER = {"data": {"summary": {"title": "Summary", "content": ""}, "sections": {
    "experience": {"items": [{"id": "x", "hidden": False, "company": "", "position": "", "location": "", "period": "",
                              "website": {"url": "", "label": "", "inlineLink": False}, "description": "", "roles": []}]},
    "skills": {"items": [{"id": "y", "hidden": False, "icon": "", "iconColor": "", "name": "", "proficiency": "", "level": 0, "keywords": []}]},
    "education": {"hidden": False, "items": []}, "certifications": {"hidden": False, "items": []}, "profiles": {"hidden": False, "items": []}}}}


def load_master_json(arg: str | None) -> dict:
    if not arg:
        return copy.deepcopy(DEFAULT_MASTER)
    master = json.loads(Path(arg).expanduser().read_text())
    try:
        master["data"]["sections"]["experience"], master["data"]["sections"]["skills"]
    except (KeyError, TypeError):
        die("--master-json must be the Master resume JSON (from the MCP tool `read_resume`): an object with "
            "data.sections.experience and data.sections.skills")
    return master


def cmd_patch(ctx: Ctx, args):
    """Lint a selection and, if it is clean, print the Reactive Resume JSON Patch operations that fill a duplicate
    of the Master: apply them unchanged with the MCP tool `apply_resume_patch` (references/reactive-resume.md,
    "Resumes"). Pass --master-json the Master's own JSON (read it first with the MCP tool `read_resume`) so field
    shapes match the instance; without it, Reactive Resume 5.x's own defaults are used."""
    path, sel = load_selection(ctx, args.job)
    issues = lint(ctx, sel)
    for lv, where, msg in issues:
        print(f"{lv} {where}: {msg}")
    errors = sum(1 for i in issues if i[0] == "E")
    (path.parent / "resume.md").write_text(render_text(ctx, sel))
    if errors:
        die(f"{errors} lint error(s); fix them (see resume.md) before patching", 1)
    target = sel.get("target") or {}
    if not (target.get("company") and target.get("role")):
        die("selection.yml needs target.company and target.role: they name the resume and its PDF", 1)
    master = load_master_json(args.master_json)
    ops = content_ops(ctx, sel, master)
    if args.sync_design:
        ops = design_ops(master) + ops
    who = str(ctx.profile.get("name") or "").strip()
    print(json.dumps({
        "resume_name": fit_name(target["company"], target["role"], who, "Resume"),
        "resume_name_full": doc_title(ctx, target),
        "resume_slug": slugify(f"{target['company']} - {target['role']}"),
        "operations": ops,
    }, indent=2))
    return 0


def cmd_cover_patch(ctx: Ctx, args):
    """Lint a cover letter and, if it is clean, print the HTML for a Reactive Resume saved cover letter: create or
    update it with the MCP tools `create_cover_letter` / `update_cover_letter` (references/reactive-resume.md,
    "Cover letters"). The job's tailored resume (`career patch`) should exist first."""
    job = ctx.job_dir(args.job)
    src = job / "cover.yml"
    if not src.exists():
        die(f"{src} not found. Write it first (see workflows/cover.md).")
    letter = yaml.safe_load(src.read_text()) or {}
    issues = lint_letter(ctx, letter, job)
    for lv, where, msg in issues:
        print(f"{lv} {where}: {msg}")
    errors = sum(1 for i in issues if i[0] == "E")
    (job / "cover.md").write_text(letter_text(ctx, letter))
    if errors:
        die(f"{errors} lint error(s); fix them (see cover.md) before patching", 1)
    recipient, content = letter_html(ctx, letter)
    print(json.dumps({
        "name": doc_title(ctx, letter.get("target") or {}, "Cover Letter")[:100],
        "recipient_html": recipient,
        "content_html": content,
    }, indent=2))
    return 0


def cmd_check(ctx: Ctx, args):
    """Local sanity check only: this script never reaches Reactive Resume. To confirm the connection itself, ask the
    assistant to call the Reactive Resume MCP tool `list_resumes`."""
    ok = True

    def step(label, cond, detail):
        nonlocal ok
        print(f"{'ok  ' if cond else 'FAIL'}  {label}: {detail}")
        ok = ok and cond

    step("data folder", ctx.root.is_dir(), str(ctx.root))
    for name in ("profile.md", "facts.md", "rules.md"):
        p = ctx.root / name
        step(name, p.exists(), str(p) if p.exists() else f"missing; run `career init`")
    master = (ctx.profile.get("rr_master") or "").strip()
    step("rr_master in profile.md", bool(master),
         master or "not set; ask the assistant to call the MCP tool `list_resumes`, find your Master, and set rr_master")
    print("Reactive Resume connection: not checked here; ask the assistant to call the MCP tool `list_resumes`.")
    return 0 if ok else 1


# ---------------------------------------------------------------- posting lookup

def _plain(h: str) -> str:
    import html as _h
    return " ".join(_h.unescape(_h.unescape(re.sub(r"<[^>]+>", " ", h or ""))).split())


def _pay_from_text(t: str) -> list:
    """Dollar ranges written into the body of a posting (pay-transparency paragraphs), with a little context.
    Amounts must look like salaries (>= $20k) and not be revenue/funding figures ($3M, $100M)."""
    out = []
    pat = r"\$\s?(\d[\d,\.]*)\s?([kKmMbB]\w*)?\s*(?:USD|CAD)?\s*(?:-|to|\u2013|\u2014|and)\s*\$?\s?(\d[\d,\.]*)\s?([kKmMbB]\w*)?(?:\s*(?:USD|CAD))?"
    for m in re.finditer(pat, t):
        def amount(n, suffix):
            try:
                v = float(n.replace(",", ""))
            except ValueError:
                return 0
            return v * 1000 if (suffix or "").lower() == "k" else v * 1e6 if (suffix or "").lower().startswith("m") else v * 1e9 if (suffix or "").lower().startswith("b") else v
        lo, hi = amount(m.group(1), m.group(2)), amount(m.group(3), m.group(4))
        if 20000 <= lo <= hi <= 2000000:
            out.append(t[max(0, m.start() - 60):m.end() + 40].strip())
    return out


def parse_posting(url: str, fetch=None) -> dict:
    """Public ATS posting APIs (no login): Ashby, Greenhouse, Lever. Returns title, location, published, pay, reports_to,
    text. `pay` is a list of sources, most reliable first; an empty list means the posting states no range."""
    fetch = fetch or (lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": USER_AGENT}), timeout=30).read()))
    u = urllib.parse.urlparse(url)
    parts = [x for x in u.path.split("/") if x]
    q = urllib.parse.parse_qs(u.query)
    res = {"url": url, "ats": None, "title": None, "location": None, "published": None, "pay": [], "reports_to": None, "text": ""}
    if "ashbyhq.com" in u.netloc and len(parts) >= 2:
        res["ats"] = "ashby"
        board, jid = parts[0], parts[1]
        for j in fetch(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true").get("jobs", []):
            if j.get("id") == jid:
                c = j.get("compensation") or {}
                if c.get("compensationTierSummary"):
                    res["pay"].append(f"structured: {c['compensationTierSummary']}")
                res.update(title=j.get("title"), location=j.get("location"), published=j.get("publishedAt"), text=_plain(j.get("descriptionHtml") or j.get("descriptionPlain")))
    elif "greenhouse.io" in u.netloc or "gh_jid" in q:
        res["ats"] = "greenhouse"
        jid = (q.get("gh_jid") or [parts[-1]])[0]
        # on a company's own domain the board token is usually ?for=, else the company name in the domain
        label = u.netloc.split(".")[-2] if u.netloc.count(".") else u.netloc
        boards = [parts[0]] if "greenhouse.io" in u.netloc else [*(q.get("for") or []), label]
        j = None
        for board in boards:
            try:
                j = fetch(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}?pay_transparency=true")
                break
            except urllib.error.HTTPError:
                continue
        if j is None:
            die(f"Greenhouse job {jid} not found on board(s) {', '.join(boards)}: closed, or the board token differs. Try the job-boards.greenhouse.io URL.")
        for r in j.get("pay_input_ranges") or []:
            res["pay"].append(f"structured: {r.get('title') or ''} {r.get('min_cents', 0) // 100}-{r.get('max_cents', 0) // 100} {r.get('currency_type') or ''}".strip())
        html_body = j.get("content") or ""
        for m in re.finditer(r'<div class="title">([^<]*)</div><div class="pay-range"><span>([^<]*)</span><span class="divider">[^<]*</span><span>([^<]*)</span>', html_body):
            res["pay"].append(f"structured: {m.group(1).strip() or 'range'}: {m.group(2)} - {m.group(3)}")
        res.update(title=j.get("title"), location=(j.get("location") or {}).get("name"), published=j.get("first_published"), text=_plain(html_body))
    elif "lever.co" in u.netloc and len(parts) >= 2:
        res["ats"] = "lever"
        j = fetch(f"https://api.lever.co/v0/postings/{parts[0]}/{parts[1]}")
        sr = j.get("salaryRange")
        if sr:
            res["pay"].append(f"structured: {sr.get('min')}-{sr.get('max')} {sr.get('currency')} {sr.get('interval')}")
        cats = j.get("categories") or {}
        lists = " ".join(f"{l.get('text', '')} {_plain(l.get('content'))}" for l in j.get("lists") or [])
        made = j.get("createdAt")
        made = dt.datetime.fromtimestamp(made / 1000, dt.timezone.utc).strftime("%Y-%m-%d") if isinstance(made, (int, float)) else made
        res.update(title=j.get("text"), location=cats.get("location"), published=made,
                   text=" ".join([j.get("descriptionPlain") or "", lists, j.get("additionalPlain") or ""]).strip())
    else:
        die("unsupported posting URL (Ashby, Greenhouse and Lever are handled); read the page and record what it says in the application's notes instead")
    res["pay"] += [f"in text: {x}" for x in _pay_from_text(res["text"])]
    m = re.search(r"(?:reports? (?:directly )?to|reporting to)\s+(?:the\s+)?([^.;]{3,70})", res["text"], re.I)
    res["reports_to"] = m.group(1).strip() if m else None
    return res


def cmd_posting(ctx: Ctx, args):
    r = parse_posting(args.url)
    if not r["title"]:
        die("that posting id is not on the board any more (closed or renumbered); check the URL")
    print(f"{r['ats']} | {r['title']} | {r['location']} | published {r['published']}")
    print("pay: " + (" || ".join(r["pay"]) if r["pay"] else "NOT STATED in the posting"))
    print(f"reports to: {r['reports_to'] or 'not stated'}")
    if args.out:
        Path(args.out).expanduser().write_text(r["text"])
        print(f"wrote {len(r['text'])} chars of description to {args.out}")
    else:
        print(r["text"][:args.chars])
    return 0


# ---------------------------------------------------------------- init / main

def cmd_init(ctx: Ctx, args):
    ctx.root.mkdir(parents=True, exist_ok=True)
    (ctx.root / "jobs").mkdir(exist_ok=True)
    for name in ("profile.md", "facts.md", "rules.md"):
        dst = ctx.root / name
        if dst.exists():
            print(f"kept existing {dst}")
        else:
            dst.write_text((ASSETS / name).read_text())
            print(f"created {dst}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="career", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="data folder (default: $CAREER_DATA or ~/Documents/Career Architect)")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for tests")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("skills").set_defaults(fn=cmd_skills)
    p = sub.add_parser("match")
    p.add_argument("--req", required=True, help="tag[:must|nice[:min_years]],... e.g. okta:must:5,terraform:nice")
    p.set_defaults(fn=cmd_match)
    p = sub.add_parser("select")
    p.add_argument("--tags", required=True, help="comma-separated tags (same string as --req works)")
    p.add_argument("--cap", type=int, help="max atoms per role (default 6 recent, 3 older)")
    p.set_defaults(fn=cmd_select)
    p = sub.add_parser("build")
    p.add_argument("job", help="jobs/<slug> name or path to selection.yml")
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("patch", help="lint a selection and print the Reactive Resume JSON Patch operations to apply with apply_resume_patch")
    p.add_argument("job")
    p.add_argument("--master-json", help="path to the Master resume JSON (from the MCP tool read_resume); omit to use Reactive Resume 5.x defaults")
    p.add_argument("--sync-design", action="store_true", help="also copy the Master's template, page, typography and layout onto this resume")
    p.set_defaults(fn=cmd_patch)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    p = sub.add_parser("cover-patch", help="lint a cover letter and print the HTML to save with create_cover_letter / update_cover_letter")
    p.add_argument("job", help="jobs/<slug> name or path")
    p.set_defaults(fn=cmd_cover_patch)
    p = sub.add_parser("posting", help="fetch a public Ashby/Greenhouse/Lever posting: pay, reports-to, description")
    p.add_argument("url")
    p.add_argument("--out", help="write the description text here (e.g. jobs/<slug>/jd.md)")
    p.add_argument("--chars", type=int, default=1500, help="how much description to print when --out is not given")
    p.set_defaults(fn=cmd_posting)
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    ctx = Ctx(args.data, today)
    return args.fn(ctx, args) or 0


if __name__ == "__main__":
    sys.exit(main())
