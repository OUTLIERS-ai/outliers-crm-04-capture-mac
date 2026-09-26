"""
ledger.py -- the event log. Layer 3.

This is the core object of the whole system: a record of what HAPPENED, one line per
occurrence, never edited. Everything descriptive about a person -- when you last
spoke, what state the relationship is in, how many exchanges there have been, how
often their details should be re-checked -- is CALCULATED from this by derive.py and
typed by nobody.

Why the inversion matters. A description states a condition at the moment somebody
wrote it. "Spoke to her recently" or "state: warm" go wrong on their own, without
anyone touching them, because keeping them current is manual work and manual work
loses to every other task you have. An event does not have that problem. "Message
sent, 4 June" is still true in ten years.

So the rule is: store what happened, calculate the rest.

THE CONTRACT

  - Append only. Lines are never edited and never deleted. A correction is a new
    event, not a rewrite. That is what makes the history impossible to quietly
    change under you.
  - One JSON object per line, so a half-written last line can only ever cost you
    that line, and a text editor can read the file.
  - Every event carries when, who, what type, and where it came from.
  - An event whose person cannot be identified is STILL recorded, with the raw
    identifiers kept. An event that cannot be attributed is a gap to investigate,
    not a thing to throw away. Dropping them makes the log look tidier and be wrong.

THE VOCABULARY IS CLOSED. An event type that is not on the list below (or in your
own settings file) is refused. An open vocabulary is how a system ends up with six
words for one thing and no query that returns the whole answer.

Use:
    import ledger
    ledger.emit("reply_received", person="rowan-ashdown", source="inbox-export")
    for e in ledger.events(person="rowan-ashdown"): ...

CLI:
    python _engine/ledger.py stats                    counts by type and by source
    python _engine/ledger.py tail [N]                 the last N events
    python _engine/ledger.py person "<identifier>"    one person's timeline
    python _engine/ledger.py types                    the event vocabulary
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings                                            # noqa: E402

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

# The base vocabulary. Deliberately small and closed. Your own additions come from
# `_engine/settings.json`, which the Layer 3 installer wrote from your answers.
BASE_TYPES = {
    "connected":        "you and they became connected",
    "message_sent":     "you sent them a message",
    "reply_received":   "they replied",
    "comment_made":     "you commented on something of theirs",
    "they_engaged":     "they engaged with something of yours",
    "call_booked":      "a call or meeting was booked",
    "meeting_held":     "a call or meeting happened",
    "joined":           "they joined something of yours",
    "went_quiet":       "nothing has happened for the length of their window",
    "details_changed":  "a re-check found a different role or company",
    "note_added":       "you wrote something down about them",
    "held":             "automatic contact suspended for this person",
    "released":         "automatic contact allowed again",
}

# Which of the base types count as CONTACT, meaning they move "last contact" and
# keep a thread alive. A details change is not contact; a message is.
BASE_CONTACT = ("message_sent", "reply_received", "meeting_held",
                "comment_made", "call_booked")


def types(root=None):
    """The full event vocabulary: the base list plus anything you added."""
    out = dict(BASE_TYPES)
    for name, spec in (settings.load(root).get("events") or {}).items():
        if name.startswith("_"):
            continue
        out[name] = (spec or {}).get("means", "one of your own event types")
    return out


def contact_types(root=None):
    """Every event type that counts as having been in contact."""
    out = set(BASE_CONTACT)
    for name, spec in (settings.load(root).get("events") or {}).items():
        if name.startswith("_"):
            continue
        if (spec or {}).get("counts_as_contact"):
            out.add(name)
    return out


def ledger_path(root=None):
    return Path(root or settings.vault_root()) / "_ledger" / "events.jsonl"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def emit(type_, person=None, source="unknown", payload=None, ts=None,
         identifiers=None, path=None, root=None):
    """Append one event. Returns the event that was written.

    `person` is the identity from Layer 2. If it is None the event is STILL written,
    carrying whatever identifiers were known at the time.
    """
    known = types(root)
    if type_ not in known:
        raise ValueError("unknown event type %r. Known types: %s"
                         % (type_, ", ".join(sorted(known))))

    ev = {
        "ts": ts or _now(),
        "type": type_,
        "person": person,
        "source": source,
    }
    if identifiers:
        ev["identifiers"] = [str(i) for i in identifiers if i]
    if payload:
        ev["payload"] = payload

    p = Path(path) if path else ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(ev, ensure_ascii=False) + "\n"
    # Append, then flush and sync. Append mode never truncates, so the worst a badly
    # timed crash can do is lose the tail of the last line, never the file.
    with open(p, "a", encoding="utf-8", newline="") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return ev


def emit_for(type_, *identifiers, **kw):
    """emit(), working out the person from whatever identifiers you happen to hold.

    This is the shape anything that collects events should use. A collector knows a
    link or a name, not an identity, and Layer 2 is the single place that maps one to
    the other. If Layer 2 cannot identify them, the event is still recorded.
    """
    person = None
    try:
        import identity
        person = identity.resolve(*identifiers)
    except Exception:
        person = None
    kw.setdefault("identifiers", list(identifiers))
    return emit(type_, person=person, **kw)


def events(person=None, type_=None, since=None, path=None, root=None):
    """Walk the log, oldest first.

    A line that cannot be read is skipped rather than raising. One bad append must
    never make the whole history unreadable.
    """
    p = Path(path) if path else ledger_path(root)
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if person and ev.get("person") != person:
                continue
            if type_ and ev.get("type") != type_:
                continue
            if since and str(ev.get("ts", "")) < str(since):
                continue
            yield ev


def last(person, only=None, path=None, root=None):
    """The most recent event for a person, optionally of certain types."""
    out = None
    for ev in events(person=person, path=path, root=root):
        if only and ev.get("type") not in only:
            continue
        out = ev
    return out


def count(person=None, type_=None, path=None, root=None):
    return sum(1 for _ in events(person=person, type_=type_, path=path, root=root))


def people(path=None, root=None):
    """Everyone the log knows about."""
    return {e["person"] for e in events(path=path, root=root) if e.get("person")}


# ------------------------------------------------------------------------- cli

def main(argv):
    cmd = argv[1] if len(argv) > 1 else "stats"
    if cmd == "stats":
        by_type, by_source, unattributed, total = {}, {}, 0, 0
        for ev in events():
            total += 1
            by_type[ev.get("type")] = by_type.get(ev.get("type"), 0) + 1
            by_source[ev.get("source")] = by_source.get(ev.get("source"), 0) + 1
            if not ev.get("person"):
                unattributed += 1
        print("log           %s" % ledger_path())
        print("events        %d" % total)
        print("people        %d" % len(people()))
        print("unattached    %d%s" % (unattributed,
              "   <- worth a look: nothing could identify these" if unattributed else ""))
        if by_type:
            print("\nby type:")
            for k, v in sorted(by_type.items(), key=lambda x: -x[1]):
                print("  %-18s %d" % (k, v))
            print("\nby source:")
            for k, v in sorted(by_source.items(), key=lambda x: -x[1]):
                print("  %-26s %d" % (k, v))
        else:
            print("\nNothing yet. Layer 4 is what fills this without you typing.")
    elif cmd == "tail":
        n = int(argv[2]) if len(argv) > 2 else 20
        for ev in list(events())[-n:]:
            print("%s  %-18s %-24s %s"
                  % (ev.get("ts", "")[:19], ev.get("type"),
                     ev.get("person") or "(unattached)", ev.get("source")))
    elif cmd == "person" and len(argv) > 2:
        try:
            import identity
            pid = identity.resolve(argv[2]) or argv[2]
        except Exception:
            pid = argv[2]
        rows = list(events(person=pid))
        print("%s: %d event(s)" % (pid, len(rows)))
        for ev in rows:
            print("  %s  %-18s %s" % (ev.get("ts", "")[:19], ev.get("type"), ev.get("source")))
    elif cmd == "types":
        known = types()
        print("%d event type(s). Anything else is refused:\n" % len(known))
        for k in sorted(known):
            print("  %-18s %s" % (k, known[k]))
    else:
        print(__doc__.replace("    python _engine/ledger.py", "    python " + _typed("ledger.py"))
              .replace("    python ", "    %s " % PY))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
