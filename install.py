"""
Outliers CRM - Layer 4 - Capture

Layer 3 gave you a log of events, and nobody writing it. If that somebody is you,
typing, you have reinvented admin, and admin is the thing that kills CRMs.

This layer fills the log from sources you already own: your messages, your calendar,
your contacts export. Nothing new to buy, nothing to sign up for.

    python install.py

It finds your CRM, asks two questions, installs the collectors, and then offers to
point one at a file so you can watch the log fill up.

Nothing here costs money and nothing leaves your computer. No account, no sign-up,
no internet connection required.

Needs: Python 3.8 or newer, and Layer 3 already installed.
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# The command a member types to start Python: `python3` on a Mac, which has no plain
# `python` command, and `python` everywhere else, as the Windows guides print it.
PY = "python3" if sys.platform == "darwin" else "python"

# The key a member presses. A Mac keyboard's key is Return; Windows keeps Enter, exactly as before
# (Mac build plan V3, wave s1: the Session 7 ruling on the words installers print).
KEY = "Return" if sys.platform == "darwin" else "Enter"

LAYER = 4
LAYER_NAME = "Capture"
NEEDS_LAYER = 3

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- small helpers

# No colour codes anywhere. Plenty of terminals print them as literal gibberish,
# and a member's first minute with this must not look broken. Plain text works
# everywhere, which is the whole point of the exercise.
BOLD = DIM = OFF = ""


def say(msg=""):
    print(msg, flush=True)


def ask(question, default=None, helptext=None):
    """One plain question. Enter accepts the default."""
    say()
    say(BOLD + question + OFF)
    if helptext:
        say(DIM + "  " + helptext + OFF)
    prompt = "  > " if default is None else "  [%s] > " % default
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        say("\nStopped. Nothing was changed.")
        sys.exit(1)
    return answer or (default or "")


def ask_yes(question, default=True):
    d = "Y/n" if default else "y/N"
    a = ask(question, default=d).strip().lower()
    if a in ("y/n", "y/n".upper(), "y", "yes"):
        return True if a != "y/n" else default
    if a in ("n", "no"):
        return False
    return default


def write(path, content):
    """Write a file without ever damaging one that already exists.

    Writes to a temporary file first, then swaps it into place in a single step.
    If anything goes wrong halfway through, the original is untouched. This is a
    habit worth keeping: the notes in here are the record, and there is no copy.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def copy_in(src, dst):
    """Install one file from this repo into the CRM, atomically."""
    write(dst, Path(src).read_text(encoding="utf-8"))



def ensure_gitignore(home, entries):
    """Add lines to the CRM's .gitignore if they are not already there.

    Never rewrites what is in there, only adds. Layer 1 put your records in this
    file so they cannot be published by accident; each layer adds whatever it
    creates that belongs in the same category.
    """
    p = Path(home) / ".gitignore"
    current = p.read_text(encoding="utf-8") if p.exists() else ""
    lines = [ln.strip() for ln in current.splitlines()]
    missing = [e for e in entries if e not in lines]
    if not missing:
        return False
    body = current
    if body and not body.endswith("\n"):
        body += "\n"
    write(p, body + "\n".join(missing) + "\n")
    return True

# ------------------------------------------------------------------ finding the CRM

def looks_like_a_crm(p):
    return (Path(p) / "_layers" / "config.json").exists()


def find_vault():
    # Layer 1 leaves a pointer in the home folder naming wherever the member chose to
    # put their CRM. Checking it first means anyone who declined the default location
    # is not told, wrongly, that they have not done Layer 1 yet.
    pointer = Path.home() / ".outliers-crm"
    guesses = []
    if pointer.exists():
        try:
            noted = pointer.read_text(encoding="utf-8").strip()
            if noted:
                guesses.append(Path(noted))
        except Exception:
            pass
    guesses += [Path.home() / "CRM", Path.cwd(), Path.cwd().parent]
    for g in guesses:
        if looks_like_a_crm(g):
            say()
            say("Found a CRM at: %s" % g)
            if ask_yes("Is that the one?", default=True):
                return Path(g)
            break
    raw = ask("Where is your CRM?",
              default=str(guesses[0]),
              helptext="The folder Layer 1 built. It has a People folder inside it.")
    return Path(raw.strip().strip('"').strip("'")).expanduser()


def previous_layer(home):
    """Return the config from the layer below, or None if this layer cannot run."""
    cfg_path = Path(home) / "_layers" / "config.json"
    if not cfg_path.exists():
        say()
        say("Layer %d needs Layer %d first. Run that one and come back."
            % (LAYER, NEEDS_LAYER))
        say()
        say("  Looked for: %s" % cfg_path)
        say("  Nothing was changed.")
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except ValueError:
        say()
        say("Layer %d needs Layer %d first. Run that one and come back."
            % (LAYER, NEEDS_LAYER))
        say()
        say("  %s exists but could not be read." % cfg_path)
        return None
    if int(cfg.get("layer", 0)) < NEEDS_LAYER:
        say()
        say("Layer %d needs Layer %d first. Run that one and come back."
            % (LAYER, NEEDS_LAYER))
        say()
        say("  That CRM is on layer %s." % cfg.get("layer"))
        return None
    return cfg


# ---------------------------------------------------------------- the interview

def interview(cfg):
    say()
    say(BOLD + "=" * 66 + OFF)
    say(BOLD + "  OUTLIERS CRM   LAYER 4   CAPTURE" + OFF)
    say(BOLD + "=" * 66 + OFF)
    say()
    say("  A collector is a small program that watches one place where things")
    say("  already happen, and writes down what it sees. That is all it is. It")
    say("  does not judge anybody, decide anything, or send anything.")
    say()
    say("  The honest warning first: fetching is easy, joining is hard. Reading")
    say("  a file of messages is straightforward. Working out that the R Ashdown")
    say("  in your calendar and the profile link in your contacts export are the")
    say("  same person is the actual difficulty, and it never goes away. That is")
    say("  what Layer 2 was for, and every collector here goes through it.")
    say()
    say(DIM + "  Press %s to accept anything in [brackets]." % KEY + OFF)

    where = ask("Where do your conversations actually happen?",
                default="",
                helptext="Separate them with commas. Email, LinkedIn, WhatsApp, "
                         "the phone, in person, a community platform. Just so the "
                         "system knows what it is missing and can tell you.")

    which = ask("Which of those can you export or connect?",
                default="",
                helptext="Most platforms have a download-your-data button somewhere. "
                         "Anything that gives you a .csv counts. " + KEY + " if you are "
                         "not sure yet, and come back to it.")

    places = [p.strip() for p in where.split(",") if p.strip()]
    exportable = [p.strip() for p in which.split(",") if p.strip()]
    return {"places": places, "exportable": exportable}


# ----------------------------------------------------------------- what we write

def layer_note(answers, home):
    missing = [p for p in answers["places"]
               if p.lower() not in [e.lower() for e in answers["exportable"]]]
    missing_text = ""
    if missing:
        missing_text = (
            "\n**What is not covered.** You said conversations also happen on: %s. "
            "Nothing is capturing those, so anything that comes from them will be "
            "missing from the log. That is worth knowing rather than discovering. "
            "Either find an export for them, or record the important ones with "
            "`%s _engine/ledger.py` yourself when they matter.\n"
            % (", ".join(missing), PY))

    return """# Layer {n} - {name}

**What it built.** Collectors, and the schedule that decides whose details to
re-check.

**What a collector is.** A small program that watches one place where things already
happen and writes down what it sees. It does not judge anybody and it does not send
anything. It reads a source you already own and turns what it finds into events.

**Fetching is easy, joining is hard.** Reading a file of messages is
straightforward. Deciding that the "R Ashdown" in your calendar, the profile link in your
contacts export and an email address are all one person is the whole difficulty, and
it never goes away.

So every collector goes through ONE resolver, the one Layer 2 installed. Not a copy
tuned for this source: the same one. Identity is decided in a single place. One
place to fix means one place that can be wrong, and when it is wrong it is wrong the
same way everywhere, which is how you find it.

**What happens to somebody you do not already have.** A provisional record for them
appears in `_staging/`, and their events attach to it, so their history is readable
from the first row. What it will NOT do is decide they are somebody you already
have: a merge is a decision about which history is right, and that decision is
yours. If a row has nothing usable in it at all, the event is still written with the
raw identifiers and nobody named. A collector that quietly discards what it cannot
place makes the log look tidier and makes every number taken from it wrong.

**Running it twice is safe.** Every row produces the same fingerprint every time,
and a fingerprint already in the log is skipped. Re-run an older export alongside a
newer one and only the new rows land.

**Refresh tiers.** What people write on a profile stops being true, and none of it
announces itself. You cannot re-check everybody and re-checking nobody lets the
whole thing rot, so the work is rationed:

| Tier | Re-checked |
|---|---|
| active | whenever you interact with them, which costs nothing extra |
| warm | on a schedule, monthly by default |
| cold | on a slower schedule, quarterly by default |

And a real event jumps the queue. Somebody who replies today goes to the front
regardless of when their turn was due. A reply matters more than a rota.
{missing}
**Where the files are.**

| File | What it is for |
|---|---|
| `_engine/collect.py` | The collectors, and the runner. |
| `_engine/refresh.py` | Who to re-check, and in what order. |
| `_engine/safe_write.py` | Writes a file without ever damaging the old one. |
| `_engine/sources.json` | The sources you named. Yours to edit. |
| `_staging/` | People a collector found that you did not already have. |

Try it:

    {py} _engine/collect.py list
    {py} _engine/collect.py run messages <file.csv> --dry-run
    {py} _engine/collect.py run messages <file.csv>
    {py} _engine/collect.py all
    {py} _engine/refresh.py due
    {py} _engine/derive.py quiet 60

**What it leaves for Layer 5.** A program can record that something happened. It
cannot tell you whether this person is worth an hour of your week, whether a reply
is warm or merely polite, or what to say back. That is judgement, and it is next.
""".format(n=LAYER, name=LAYER_NAME, missing=missing_text, py=PY)


def staging_readme():
    return """# Waiting to be sorted out

A collector found these people and did not already have a record for them. Rather
than decide they were somebody you already had, it made a provisional record here.

Nothing in this folder is settled. Each file says which identifiers it arrived with.

**If they are somebody you already have:** add whichever identifier is missing to
their existing record in `People/` (usually to the `aliases` list), and delete the
file here. Next time a collector meets them, it will place them correctly.

**If they are new:** move the file into `People/` and fill in what you know.

**If you do not care:** leave them. Nothing here is used for anything until you move
it, and the folder costs nothing.

The reason it works this way is that a wrong merge is worse than a missed one. A
miss shows up here, where you can see it. A wrong merge silently mixes two people's
histories together and there is no way back.
"""


# ------------------------------------------------------------------------- build

def build(home, answers):
    say()
    say(BOLD + "Installing Layer %d into %s" % (LAYER, home) + OFF)
    say()

    def note(path, what):
        say("  wrote  %-40s %s"
            % (str(Path(path).relative_to(home)).replace("\\", "/"), what))

    engine = home / "_engine"

    for name, what in (("safe_write.py", "writes a file without damaging the old one"),
                       ("collect.py", "the collectors, and the runner"),
                       ("refresh.py", "who to re-check, and in what order")):
        p = engine / name
        copy_in(HERE / "crm" / name, p)
        note(p, what)

    # The re-check schedule needs an event type meaning "their details were looked
    # at". Adding it here rather than editing Layer 3's code is the point of having
    # the vocabulary in a settings file.
    sp = engine / "settings.json"
    s = {}
    if sp.exists():
        try:
            s = json.loads(sp.read_text(encoding="utf-8"))
        except ValueError:
            s = {}
    s.setdefault("events", {})
    s["events"].setdefault("checked", {
        "means": "their details were re-checked and nothing had changed",
        "counts_as_contact": False,
    })
    s.setdefault("refresh_days", {"active": 0, "warm": 30, "cold": 90})
    write(sp, json.dumps(s, indent=2) + "\n")
    note(sp, "now knows what a re-check is")

    p = engine / "sources.json"
    existing = []
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8")).get("sources", [])
        except ValueError:
            existing = []
    write(p, json.dumps({
        "_comment": [
            "The sources you capture from. `%s _engine/collect.py all` runs each "
            "one in turn." % PY,
            "collector must be one of: messages, meetings, connections.",
            "Running the same file twice is safe: rows already in the log are skipped.",
        ],
        "conversations_happen_on": answers["places"],
        "can_be_exported": answers["exportable"],
        "sources": existing,
    }, indent=2) + "\n")
    note(p, "the sources you named. yours to edit")

    (home / "_staging").mkdir(parents=True, exist_ok=True)
    sr = home / "_staging" / "README.md"
    write(sr, staging_readme())
    note(sr, "what to do with people you did not already have")

    p = home / "_layers" / ("Layer %d - %s.md" % (LAYER, LAYER_NAME))
    write(p, layer_note(answers, home))
    note(p, "what this layer did, for when you forget")

    if ensure_gitignore(home, ["_staging/", "__pycache__/", "*.pyc"]):
        say("  added  %-40s keeps staged people off any public copy" % (".gitignore",))

    cfg_path = home / "_layers" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.update({
        "layer": max(int(cfg.get("layer", 1)), LAYER),
        "conversations_happen_on": answers["places"],
        "can_be_exported": answers["exportable"],
        "layer_%d_installed" % LAYER: date.today().isoformat(),
    })
    write(cfg_path, json.dumps(cfg, indent=2) + "\n")
    note(cfg_path, "records that Layer %d is in" % LAYER)


# --------------------------------------------------------------------- now use it

def guess_collector(path):
    """Work out which collector suits a file, from its column names."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            head = "\n".join(fh.readline() for _ in range(15)).lower()
    except OSError:
        return None
    if "connected on" in head or ("first name" in head and "url" in head):
        return "connections"
    if any(k in head for k in ("attendee", "invitee", "start time", "event type",
                               "subject", "start")):
        return "meetings"
    if any(k in head for k in ("direction", "sent at", "message", "conversation",
                               "from", "sender")):
        return "messages"
    return None


def needs_your_name(path):
    """True when the file says who sent each message but not which way it went."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            head = fh.readline().lower()
    except OSError:
        return False
    has_direction = "direction" in head
    has_sender = any(k in head for k in ("from", "sender", "author"))
    return has_sender and not has_direction


def point_it_at_something(home, answers):
    """The point of the layer: a source they already own, filling the log."""
    say()
    say(BOLD + "-" * 66 + OFF)
    say(BOLD + "  Now point it at something" + OFF)
    say(BOLD + "-" * 66 + OFF)
    say()
    say("  This is the part where the CRM starts giving something back. Find a")
    say("  .csv you already have: a contacts or connections export, a calendar")
    say("  export, a message export. Any of them.")
    say()
    say("  It will read it without writing anything first, and tell you what it")
    say("  would do. Nothing lands until you say so.")

    raw = ask("Path to the file, or %s to skip" % KEY, default="")
    if not raw.strip():
        say(DIM + "  Skipped. When you have one:" + OFF)
        say(DIM + "    %s _engine/collect.py run connections <file.csv> --dry-run" % PY + OFF)
        return None

    path = Path(raw.strip().strip('"').strip("'")).expanduser()
    if not path.exists():
        say("  Cannot find that file. Skipping; you can run it later with:")
        say("    %s _engine/collect.py run connections <file.csv>" % PY)
        return None

    kind = guess_collector(path)
    if kind:
        say()
        say("  That looks like a %s export." % kind)
        if not ask_yes("Read it as %s?" % kind, default=True):
            kind = None
    if not kind:
        kind = ask("Which is it: messages, meetings or connections?",
                   default="connections").strip().lower()
    if kind not in ("messages", "meetings", "connections"):
        say("  Not one of the three. Skipping; nothing was changed.")
        return None

    you = ""
    if kind == "messages" and needs_your_name(path):
        you = ask("That file says who sent each message but not which way it went. "
                  "What name do you appear under in it?",
                  default="",
                  helptext="So it can tell your messages from theirs. " + KEY + " to "
                           "treat every row as one of yours.")

    sys.path.insert(0, str(home / "_engine"))
    os.environ["OUTLIERS_CRM_VAULT"] = str(home)
    try:
        import collect
    except ImportError as e:
        say("  Could not load the collectors (%s). They are installed; run them "
            "yourself." % e)
        return None

    say()
    say("  Reading it. Nothing is being written.")
    stats = collect.run(kind, path, dry_run=True, root=home, you=you or None)
    say()
    say("    rows read           %d" % stats["read"])
    say("    would be recorded   %d" % (stats["read"] - stats["skipped"]
                                        - stats["already there"]))
    say("    already in the log  %d" % stats["already there"])
    say("    people you have     %d" % (stats["read"] - stats["skipped"]
                                        - stats["already there"]
                                        - stats["new people"]))
    say("    people you do not   %d" % stats["new people"])
    say("    skipped             %d" % stats["skipped"])
    for why, n in (stats.get("_reasons") or {}).items():
        say("        %-26s %d" % (why, n))
    say()
    if stats["new people"]:
        say("  The ones you do not already have get a provisional record each in")
        say("  _staging, and their events attach to it, so you can read their")
        say("  history straight away. None of them is merged into anybody you")
        say("  already had. A wrong merge is worse than a missed one, and deciding")
        say("  which history is right is yours to do.")
        say()

    if not ask_yes("Write those to the log?", default=True):
        say("  Nothing written.")
        return None

    real = collect.run(kind, path, root=home, you=you or None)
    say()
    say("  written        %d" % real["written"])
    say("  staged         %d" % real["staged"])

    p = home / "_engine" / "sources.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["sources"] = [s for s in doc.get("sources", []) if s.get("path") != str(path)]
    doc["sources"].append({"name": path.name, "collector": kind, "path": str(path)})
    write(p, json.dumps(doc, indent=2) + "\n")
    say("  remembered     %s, so `collect.py all` picks it up next time" % path.name)
    return real


def read_a_history(home):
    """Look up somebody and read a history nobody typed."""
    sys.path.insert(0, str(home / "_engine"))
    os.environ["OUTLIERS_CRM_VAULT"] = str(home)
    try:
        import identity
        import ledger
        import derive
    except ImportError:
        return

    if not list(ledger.events(root=home)):
        return

    say()
    say(BOLD + "-" * 66 + OFF)
    say(BOLD + "  Look somebody up" + OFF)
    say(BOLD + "-" * 66 + OFF)
    say()
    say("  Pick somebody you had half forgotten. What comes back was typed by")
    say("  nobody.")
    who = ask("A name, a link or an email address (or %s to skip)" % KEY, default="")
    if not who.strip():
        say(DIM + "  Skipped. Any time:  %s _engine/ledger.py person \"a name\"" % PY + OFF)
        return
    identity.forget()
    pid = identity.resolve(who.strip(), vault=home)
    if not pid:
        say()
        say("  Not found, and deliberately not guessed at. Either they are not in")
        say("  your records, or that name belongs to two people.")
        return
    rows = list(ledger.events(person=pid, root=home))
    say()
    say("  %s: %d event(s)" % (pid, len(rows)))
    for ev in rows[-15:]:
        say("    %s  %-16s %s" % (ev.get("ts", "")[:10], ev.get("type"), ev.get("source")))
    st = derive.person_state(pid, root=home)
    if st:
        say()
        say("  And from those events, calculated, typed by nobody:")
        for k in ("last-contact", "conversation-points", "relationship-state",
                  "refresh-tier", "next-contact-due"):
            if st.get(k) is not None:
                say("    %-22s %s" % (k, st[k]))


def finish(home, answers):
    say()
    say(BOLD + "=" * 66 + OFF)
    say(BOLD + "  Done. Your CRM fills itself." + OFF)
    say(BOLD + "=" * 66 + OFF)
    say()
    say("  What changed:")
    say("    - Three collectors, all going through the one resolver.")
    say("    - A re-check schedule, with real events jumping the queue.")
    say("    - A _staging folder for anyone the collectors did not already have.")
    say()
    missing = [p for p in answers["places"]
               if p.lower() not in [e.lower() for e in answers["exportable"]]]
    if missing:
        say("  Not covered: %s." % ", ".join(missing))
        say("  Conversations there will be missing from the log. Worth knowing")
        say("  rather than discovering later.")
        say()
    say("  Try:")
    say("    %s _engine/collect.py all         re-run every source" % PY)
    say("    %s _engine/refresh.py due         whose details need a look" % PY)
    say("    %s _engine/derive.py quiet 60     who has gone quiet" % PY)
    say()
    say("  Read: _layers/Layer %d - %s.md" % (LAYER, LAYER_NAME))
    say()
    say(BOLD + "  What Layer 5 does." + OFF)
    say("  A program can record that something happened. It cannot tell you")
    say("  whether this person is worth an hour of your week, whether a reply is")
    say("  warm or merely polite, or what to say back. That is judgement.")
    say()


def main():
    say()
    say("  Outliers CRM, Layer %d: %s" % (LAYER, LAYER_NAME))
    home = find_vault()
    cfg = previous_layer(home)
    if cfg is None:
        return 1

    answers = interview(cfg)

    say()
    say("  Installing into:      %s" % home)
    say("  Conversations happen: %s"
        % (", ".join(answers["places"]) or "not said"))
    say("  Can be exported:      %s"
        % (", ".join(answers["exportable"]) or "not said"))
    if not ask_yes("Go ahead?", default=True):
        say("\nStopped. Nothing was changed.")
        return 1

    build(home, answers)
    point_it_at_something(home, answers)
    read_a_history(home)
    finish(home, answers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
