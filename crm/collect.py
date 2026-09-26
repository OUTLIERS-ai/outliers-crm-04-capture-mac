"""
collect.py -- filling the log without typing. Layer 4.

A collector is a small program that watches one place where things already happen
and writes down what it sees. That is the whole definition. It does not decide
anything, it does not judge anybody, it does not send anything. It reads a source
you already own and turns what it finds into events.

FETCHING IS EASY. JOINING IS HARD.

Reading a file of messages is straightforward. Deciding that the "R. Ashdown" in
the calendar, the profile link in the connections export and the address
rowan@ashdown.example are all one person is the entire difficulty, and it never goes
away. Every source names people differently, one human turns up as four different
identifiers, and two different humans share a name.

So every collector here goes through ONE resolver, the one Layer 2 installed. Not a
copy of it, not a slightly different version tuned for this source: the same one.
Identity gets decided in a single place. One place to fix means one place that can
be wrong, and when it is wrong, it is wrong the same way everywhere, which is how
you find it.

WHAT HAPPENS TO SOMEBODY IT DOES NOT ALREADY HAVE

It writes a provisional record for them into `_staging/`, and the event attaches to
that. What it will NOT do is decide that they are somebody you already have. A new
record is a new person until you say otherwise; a merge is a decision about which
history is right, and that is yours.

If there is not even enough in the row to make a record from, the event is still
written with the raw identifiers and nobody named. Nothing is thrown away. A
collector that discards what it cannot place makes the log look tidier and makes
every count taken from it wrong.

RUNNING IT TWICE IS SAFE

Every row a collector reads produces the same fingerprint every time. A fingerprint
already in the log is skipped. So you can re-run an older export alongside a newer
one, and only the new rows land. That property matters more than speed: a
collector that double-counts corrupts every number derived from it, and the numbers
are the point.

Use:
    python _engine/collect.py list                          the collectors you have
    python _engine/collect.py run messages <file.csv> --dry-run
    python _engine/collect.py run messages <file.csv>
    python _engine/collect.py all                           every source in sources.json
"""

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ledger                                              # noqa: E402
import settings                                            # noqa: E402
from safe_write import write_text                          # noqa: E402

# The command a member types to start Python: `python3` on a Mac, which has no plain
# `python` command, and `python` everywhere else, as the Windows guides print it.
PY = "python3" if sys.platform == "darwin" else "python"


def _typed(name):
    """The program `name` (it sits beside this file) as the member types it from the folder
    they are in: `_engine/<name>` from the CRM folder, `<name>` from inside `_engine`."""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    try:
        typed = os.path.relpath(path)
    except ValueError:                      # the member is on another drive
        typed = path
    if typed.startswith(".."):
        typed = path
    typed = typed.replace("\\", "/")
    return '"%s"' % typed if " " in typed else typed

try:
    import identity
except ImportError:                                        # Layer 2 not installed
    identity = None


def sources_path(root=None):
    return Path(root or settings.vault_root()) / "_engine" / "sources.json"


def sources(root=None):
    p = sources_path(root)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("sources", [])
    except ValueError:
        return []


# --------------------------------------------------------------- reading a csv

def _open_rows(path):
    """Yield dict rows from a CSV, tolerating the junk real exports carry.

    Exports frequently put a few lines of preamble above the real header row, use a
    byte-order mark, and mix casing between columns. This finds the header and reads
    from there.
    """
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        start = 0
        for i, line in enumerate(sample.splitlines()[:15]):
            low = line.lower()
            if low.count(",") >= 1 and any(k in low for k in (
                    "name", "email", "date", "time", "url", "profile",
                    "attendee", "subject", "from", "to")):
                start = i
                break
        for _ in range(start):
            fh.readline()
        for row in csv.DictReader(fh):
            yield {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items() if k}


def _pick(row, *names):
    """The first column present out of the ones named, else ""."""
    for n in names:
        if row.get(n):
            return row[n]
    for n in names:                                        # then a partial match
        for k, v in row.items():
            if v and n in k:
                return v
    return ""


def _as_date(value):
    """Any of the usual date spellings, as an ISO timestamp, else "".

    Exports differ on this more than anything else. Anything unreadable returns
    empty and the row is skipped and counted, rather than being given a made-up date.
    """
    s = str(value or "").strip()
    if not s:
        return ""
    s = s.replace("/", "-").replace(".", "-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})", s)
        if not m:
            m2 = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})", s)
            if not m2:
                return ""
            months = ["jan", "feb", "mar", "apr", "may", "jun",
                      "jul", "aug", "sep", "oct", "nov", "dec"]
            try:
                mo = str(months.index(m2.group(2)[:3].lower()) + 1)
            except ValueError:
                return ""
            d, y = m2.group(1), m2.group(3)
        else:
            d, mo, y = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), 12, 0, 0, tzinfo=timezone.utc)
    except ValueError:
        return ""
    time = re.search(r"(\d{1,2}):(\d{2})", s)
    if time:
        try:
            dt = dt.replace(hour=int(time.group(1)), minute=int(time.group(2)))
        except ValueError:
            pass
    return dt.isoformat(timespec="seconds")


def _name_of(row):
    first = _pick(row, "first name", "firstname", "given name")
    last = _pick(row, "last name", "lastname", "surname", "family name")
    joined = " ".join(x for x in (first, last) if x).strip()
    return joined or _pick(row, "name", "full name", "attendee", "contact",
                           "person", "invitee")


def _identifiers(row):
    out = []
    for v in (_pick(row, "url", "profile url", "profile", "linkedin", "link"),
              _pick(row, "email", "email address", "e-mail", "invitee email"),
              _pick(row, "phone", "mobile", "telephone"),
              _name_of(row)):
        if v and v not in out:
            out.append(v)
    return out


# ------------------------------------------------------------------ collectors
# Each one turns rows of a source into events. They do nothing else: no judgement,
# no scoring, no sending.

def from_messages(path, you):
    """A message export: one row per message.

    Whether a message was yours or theirs is worked out from a direction column if
    there is one, otherwise from whether the sender is you. Message CONTENT is never
    read into the log. What happened and when is the useful part; keeping copies of
    what was said is a liability nobody needs.
    """
    for row in _open_rows(path):
        ts = _as_date(_pick(row, "date", "sent at", "timestamp", "time", "date sent"))
        ident = _identifiers(row)
        if not ident:
            yield {"skip": "no identifier"}
            continue
        if not ts:
            yield {"skip": "no readable date"}
            continue

        # Whose message it was. Matched on whole words: "outgoing" contains the
        # letters of "in", which is the sort of thing that silently reverses every
        # row in a file and is not obvious afterwards.
        direction = _pick(row, "direction", "type").strip().lower()
        sender = _pick(row, "from", "sender", "author").strip().lower()
        outgoing = True
        if direction:
            if direction.startswith("out") or "sent" in direction or direction == "you":
                outgoing = True
            elif (direction.startswith("in") or "received" in direction
                    or "reply" in direction or "them" in direction):
                outgoing = False
        elif sender:
            outgoing = bool(you) and you.lower() in sender

        yield {
            "type": "message_sent" if outgoing else "reply_received",
            "ts": ts,
            "identifiers": ident,
            "fingerprint": "message|%s|%s|%s" % (ts[:16], ident[0].lower(),
                                                 "out" if outgoing else "in"),
            "payload": {},
        }


def from_meetings(path, you=None):
    """A calendar or booking export: one row per meeting.

    A meeting in the past is one that happened. A meeting in the future is one that
    is booked. They are different events because they mean different things: a
    booking is a promise, a meeting is a fact.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in _open_rows(path):
        ts = _as_date(_pick(row, "start", "date", "start time", "when", "created"))
        ident = _identifiers(row)
        if not ident:
            yield {"skip": "no identifier"}
            continue
        if not ts:
            yield {"skip": "no readable date"}
            continue
        happened = ts <= now
        yield {
            "type": "meeting_held" if happened else "call_booked",
            "ts": ts,
            "identifiers": ident,
            "fingerprint": "meeting|%s|%s" % (ts[:16], ident[0].lower()),
            "payload": {"subject": _pick(row, "subject", "title", "event", "event type")},
        }


def from_connections(path, you=None):
    """A connections or contacts export: one row per person.

    The date a connection was made is a real event. This is usually the biggest and
    dullest source anybody has, and it is the one that makes the rest of the system
    useful, because it is what gives most people a record at all.
    """
    for row in _open_rows(path):
        ident = _identifiers(row)
        if not ident:
            yield {"skip": "no identifier"}
            continue
        ts = _as_date(_pick(row, "connected on", "date", "created", "added"))
        yield {
            "type": "connected",
            "ts": ts or None,
            "identifiers": ident,
            "fingerprint": "connected|%s" % ident[0].lower(),
            "payload": {k: v for k, v in
                        (("company", _pick(row, "company", "organisation", "organization")),
                         ("role", _pick(row, "position", "title", "role", "headline")))
                        if v},
        }


COLLECTORS = {
    "messages": (from_messages,
                 "a message export: one row per message sent or received"),
    "meetings": (from_meetings,
                 "a calendar or booking export: one row per meeting"),
    "connections": (from_connections,
                    "a contacts or connections export: one row per person"),
}


# ------------------------------------------------------------------- the runner

def _seen_fingerprints(path=None, root=None):
    """Every fingerprint already in the log, so re-running a source is a no-op."""
    out = set()
    for ev in ledger.events(path=path, root=root):
        fp = (ev.get("payload") or {}).get("fingerprint")
        if fp:
            out.add(fp)
    return out


def _identity_of(ident):
    """The identity a new record made from these identifiers would have.

    The same order the resolver uses, so a record staged now is found by the
    resolver next time without anything having to agree twice.
    """
    if identity is None:
        return None
    for i in ident:
        s = identity.slug(i)
        if s:
            return s
    for i in ident:
        e = identity.norm_email(i)
        if e:
            return "email:" + e
    for i in ident:
        p = identity.norm_phone(i)
        if p:
            return "phone:" + p
    for i in ident:
        n = identity.norm_name(i)
        if n:
            return "name:" + n
    return None


def _remember(local, ident, pid):
    """Note the people staged during THIS run, so the second row about somebody
    finds the record the first row created without re-reading every file."""
    if identity is None or not pid:
        return
    for i in ident:
        for key in (identity.slug(i), identity.norm_email(i),
                    identity.norm_phone(i), identity.norm_name(i)):
            if key:
                local.setdefault(key, pid)


def _recall(local, ident):
    if identity is None:
        return None
    for i in ident:
        for key in (identity.slug(i), identity.norm_email(i),
                    identity.norm_phone(i), identity.norm_name(i)):
            if key and key in local:
                return local[key]
    return None


def _staging_record(root, ident, payload):
    """Write a record for somebody the resolver could not identify.

    Not into People/. They go to `_staging/`, because a person the system invented
    from one line of an export is a suggestion, not a record. You look at them, and
    the ones that are real you move across.
    """
    name = ""
    for i in ident:
        if "@" not in str(i) and "/" not in str(i) and not str(i).isdigit():
            name = str(i)
            break
    safe = re.sub(r'[<>:"/\\|?*]', "", name or "unidentified").strip()[:80] or "unidentified"
    target = Path(root) / "_staging" / (safe + ".md")
    if target.exists():
        return None
    link = next((i for i in ident if "linkedin.com/in/" in str(i).lower()), "")
    email = next((i for i in ident if "@" in str(i)), "")
    write_text(target, """---
name: {name}
linkedin-url: {link}
email: {email}
aliases: []
company: {company}
role: {role}
date: {today}
type: prospect
tags: [crm, staged]
---

## Who they are

Found by a collector, and nothing could work out whether they are already in your
records. Nothing was guessed. If this is somebody you already have, add whichever
identifier is missing to their existing record and delete this one. If they are new,
move this file into People.

Found as: {found}
""".format(name=name or "(unknown)", link=link, email=email,
           company=(payload or {}).get("company", ""),
           role=(payload or {}).get("role", ""),
           today=datetime.now(timezone.utc).date().isoformat(),
           found=", ".join(str(i) for i in ident)))
    return target


def run(kind, path, dry_run=False, root=None, ledger_file=None, you=None):
    """Run one collector over one file. Returns a summary of what happened."""
    if kind not in COLLECTORS:
        raise ValueError("no collector called %r. Known: %s"
                         % (kind, ", ".join(sorted(COLLECTORS))))
    fn = COLLECTORS[kind][0]
    root = Path(root or settings.vault_root())
    if you is None:
        cfg = root / "_layers" / "config.json"
        if cfg.exists():
            try:
                you = json.loads(cfg.read_text(encoding="utf-8")).get("your_name", "")
            except ValueError:
                you = ""

    seen = _seen_fingerprints(path=ledger_file, root=root)
    stats = {"read": 0, "written": 0, "already there": 0, "new people": 0,
             "staged": 0, "nobody attached": 0, "skipped": 0}
    reasons = {}
    local = {}                    # people staged during this run

    for row in fn(path, you):
        stats["read"] += 1
        if row.get("skip"):
            stats["skipped"] += 1
            reasons[row["skip"]] = reasons.get(row["skip"], 0) + 1
            continue
        fp = row["fingerprint"]
        if fp in seen:
            stats["already there"] += 1
            continue

        pid = None
        if identity is not None:
            try:
                pid = identity.resolve(*row["identifiers"], vault=root)
            except Exception:
                pid = None
        if not pid:
            pid = _recall(local, row["identifiers"])
        if not pid:
            stats["new people"] += 1

        if dry_run:
            seen.add(fp)
            continue

        if not pid:
            # Somebody you do not already have. A provisional record goes to
            # _staging and the event attaches to it, so their history is readable
            # from the first row. It is NOT merged into anybody: a merge is a
            # decision about which history is right, and that decision is yours.
            if _staging_record(root, row["identifiers"], row.get("payload")):
                stats["staged"] += 1
            pid = _identity_of(row["identifiers"])
            _remember(local, row["identifiers"], pid)
            if not pid:
                stats["nobody attached"] += 1

        payload = dict(row.get("payload") or {})
        payload["fingerprint"] = fp
        ledger.emit(row["type"], person=pid, source="collector:" + kind,
                    ts=row.get("ts"), payload=payload,
                    identifiers=row["identifiers"], path=ledger_file, root=root)
        seen.add(fp)
        stats["written"] += 1

    if identity is not None and stats["staged"]:
        identity.forget()         # the next question should see what just arrived
    stats["_reasons"] = reasons
    return stats


def run_all(dry_run=False, root=None, ledger_file=None):
    """Run every source listed in `_engine/sources.json`."""
    out = {}
    for s in sources(root):
        p = Path(s.get("path", "")).expanduser()
        if not p.exists():
            out[s.get("name") or str(p)] = {"error": "file not found: %s" % p}
            continue
        out[s.get("name") or str(p)] = run(s["collector"], p, dry_run=dry_run,
                                           root=root, ledger_file=ledger_file)
    return out


# ------------------------------------------------------------------------- cli

def _report(label, stats):
    print("\n%s" % label)
    if "error" in stats:
        print("  %s" % stats["error"])
        return
    for k in ("read", "written", "already there", "new people", "staged",
              "nobody attached", "skipped"):
        print("  %-18s %d" % (k, stats.get(k, 0)))
    for why, n in (stats.get("_reasons") or {}).items():
        print("      skipped, %-24s %d" % (why, n))
    if stats.get("staged"):
        print("\n  New people have a provisional record each in _staging/. Nothing")
        print("  was merged into anybody you already had. Look at them and decide.")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    dry = "--dry-run" in argv
    if cmd == "list":
        print("collectors:\n")
        for k, (_, what) in sorted(COLLECTORS.items()):
            print("  %-14s %s" % (k, what))
        srcs = sources()
        print("\nsources you named at install: %d" % len(srcs))
        for s in srcs:
            print("  %-14s %-12s %s"
                  % (s.get("name", ""), s.get("collector", ""), s.get("path", "")))
    elif cmd == "run" and len(argv) > 3:
        kind, path = argv[2], Path(argv[3]).expanduser()
        if not path.exists():
            print("no such file: %s" % path)
            return 1
        _report("%s <- %s%s" % (kind, path, "   (dry run, nothing written)" if dry else ""),
                run(kind, path, dry_run=dry))
    elif cmd == "all":
        results = run_all(dry_run=dry)
        if not results:
            print("No sources listed. Add one:")
            print("  %s %s run messages <file.csv>" % (PY, _typed("collect.py")))
            return 0
        for label, stats in results.items():
            _report(label + ("   (dry run, nothing written)" if dry else ""), stats)
    else:
        print(__doc__.replace("    python _engine/collect.py", "    python " + _typed("collect.py"))
              .replace("    python ", "    %s " % PY))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
