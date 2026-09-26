"""
refresh.py -- deciding whose details to re-check, and when. Layer 4.

What people write on a profile stops being true. They change job, the company gets
bought, the title changes, they move country. None of it announces itself. So the
facts in your CRM rot, quietly, at a rate you cannot see.

You cannot re-check everybody, and re-checking nobody means the whole thing is out
of date within a year or two. So the work is rationed by tier.

    active   re-checked whenever you interact with them
    warm     re-checked on a schedule, monthly by default
    cold     re-checked on a slower schedule, quarterly by default

The tier comes from the relationship state, which comes from the event log, which
means it is not a judgement anybody has to make. Somebody you are actually talking
to gets re-checked constantly and it costs nothing extra, because you were looking
at them anyway. The schedule only pays for the people you are not talking to.

A REAL EVENT JUMPS THE QUEUE.

If somebody replies today, they go to the front regardless of when their turn was
due. A reply matters more than a schedule, always. The schedule exists to catch the
people nothing is happening with; it should never hold up somebody something IS
happening with.

WHAT THIS DOES NOT DO

It does not go and look. It produces the list of who to look at, in order. Actually
fetching a page is a separate job, and one you may want to do by hand, or with a
tool, or not at all. Keeping the two apart means the ranking can be trusted on its
own and tested without touching a network.

Use:
    python _engine/refresh.py due               who is due a re-check, most overdue first
    python _engine/refresh.py tiers             how many people are on each tier
    python _engine/refresh.py checked "<who>"   record that you have re-checked somebody
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import derive                                              # noqa: E402
import ledger                                              # noqa: E402
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

# Events that mean "their details were looked at on this date".
CHECK_EVENTS = ("checked", "details_changed")

# Events that mean something real happened and they should be looked at now.
JUMP_EVENTS = ("reply_received", "meeting_held", "call_booked", "joined")

# Anybody with one of those outranks everybody on the schedule, however overdue the
# schedule is. Two separate number ranges is the simplest way to guarantee that.
JUMP_PRIORITY = 1000000
NEVER_CHECKED_PRIORITY = 500000


def _days_since(ts):
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if not t.tzinfo:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).days


def last_checked(pid, path=None, root=None):
    """When this person's details were last confirmed, or None if never."""
    out = None
    for ev in ledger.events(person=pid, path=path, root=root):
        if ev.get("type") in CHECK_EVENTS:
            out = ev.get("ts")
    return out


def _first_seen(pid, path=None, root=None):
    for ev in ledger.events(person=pid, path=path, root=root):
        return ev.get("ts")
    return None


def status(pid, path=None, root=None):
    """Whether this person is due a re-check, and why."""
    st = derive.person_state(pid, path=path, root=root)
    if not st:
        return None

    windows = settings.load(root).get("refresh_days") or {}
    tier = st.get("refresh-tier", "cold")
    window = int(windows.get(tier, 90) or 0)

    checked = last_checked(pid, path=path, root=root)
    since_checked = _days_since(checked) if checked else _days_since(
        _first_seen(pid, path=path, root=root))

    row = {
        "person": pid,
        "tier": tier,
        "window": window,
        "last-checked": (checked or "")[:10] or None,
        "days-since-checked": since_checked,
        "relationship-state": st.get("relationship-state"),
        "due": False,
        "reason": "",
        "priority": 0,
    }

    # A real event jumps the queue. Anything that happened since the last check, of
    # a kind that means they did something, puts them at the front.
    jumped = None
    for ev in ledger.events(person=pid, path=path, root=root):
        if ev.get("type") not in JUMP_EVENTS:
            continue
        if checked and str(ev.get("ts", "")) <= str(checked):
            continue
        jumped = ev
    if jumped:
        row["due"] = True
        row["reason"] = "%s since you last checked" % jumped.get("type")
        # Deliberately on a different scale from the schedule below, so that no
        # amount of being overdue on the rota can outrank something that actually
        # happened. Within the jumpers, the most recent comes first.
        row["priority"] = JUMP_PRIORITY - min(_days_since(jumped.get("ts")) or 0,
                                              JUMP_PRIORITY - 1)
        return row

    if window == 0:
        # The active tier has no schedule of its own. You see these people anyway.
        row["reason"] = "on the active tier, re-checked when you interact"
        return row

    if since_checked is None:
        row["due"] = True
        row["reason"] = "never checked"
        row["priority"] = NEVER_CHECKED_PRIORITY
        return row

    if since_checked >= window:
        row["due"] = True
        row["reason"] = "%d days since the last check, %s window is %d" % (
            since_checked, tier, window)
        row["priority"] = since_checked - window
        return row

    row["reason"] = "next check in %d days" % (window - since_checked)
    return row


def due(path=None, root=None):
    """Everybody due a re-check, most urgent first."""
    rows = []
    for pid in ledger.people(path=path, root=root):
        r = status(pid, path=path, root=root)
        if r and r["due"]:
            rows.append(r)
    return sorted(rows, key=lambda r: -r["priority"])


def tiers(path=None, root=None):
    """How many people sit on each tier."""
    out = {}
    for pid in ledger.people(path=path, root=root):
        r = status(pid, path=path, root=root)
        if r:
            out[r["tier"]] = out.get(r["tier"], 0) + 1
    return out


def mark_checked(pid, source="by hand", changed=False, path=None, root=None,
                 payload=None):
    """Record that you have re-checked somebody.

    `changed=True` records that what you found was different from what you had,
    which is a more interesting event than a check that found nothing new.
    """
    return ledger.emit("details_changed" if changed else "checked",
                       person=pid, source=source, payload=payload,
                       path=path, root=root)


# ------------------------------------------------------------------------- cli

def main(argv):
    cmd = argv[1] if len(argv) > 1 else "due"
    if cmd == "due":
        rows = due()
        print("Due a re-check: %d\n" % len(rows))
        for r in rows[:60]:
            print("  %-30s %-7s %s" % (r["person"][:30], r["tier"], r["reason"]))
        if len(rows) > 60:
            print("  ... and %d more" % (len(rows) - 60))
        if not rows:
            print("  Nobody. Either everything is fresh, or the log is empty.")
            print("  `%s %s stats` says which." % (PY, _typed("ledger.py")))
    elif cmd == "tiers":
        t = tiers()
        total = sum(t.values())
        print("people the log knows about: %d\n" % total)
        for k in ("active", "warm", "cold"):
            if k in t:
                print("  %-8s %5d" % (k, t[k]))
        if not total:
            print("  Nothing yet. Run a collector first.")
    elif cmd == "checked" and len(argv) > 2:
        try:
            import identity
            pid = identity.resolve(argv[2]) or argv[2]
        except Exception:
            pid = argv[2]
        changed = "--changed" in argv
        mark_checked(pid, source="by hand", changed=changed)
        print("recorded: %s %s" % (pid, "details changed" if changed else "checked"))
    else:
        print(__doc__.replace("    python _engine/refresh.py", "    python " + _typed("refresh.py"))
              .replace("    python ", "    %s " % PY))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
