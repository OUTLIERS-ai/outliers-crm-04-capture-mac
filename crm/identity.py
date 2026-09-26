"""
identity.py -- the single place that answers "which person is this?"

Layer 2 of the CRM. Everything built above this joins through the identity this
module hands back: holds, eligibility, duplicate detection, capture, attribution.

Why it has to be one place. If each part of the system decides for itself which
record a person is, each one decides differently. One matches on a filename, one on
a display name, one on a profile link, one on an email address. They then disagree
about the same human, and the disagreement is invisible until something goes wrong
in a way nobody can explain. A hold recorded under a name, for example, is invisible
to a caller that only holds a profile link, because a matcher can only match on what
it is given.

THE ORDER (never varies):

    1. profile slug          strong, deterministic
    2. email address         strong, deterministic
    3. phone number          strong, deterministic
    4. alias list            an identifier already recorded against a known person
    5. full display name     ONLY when it is unique in your records
    6. otherwise             None. An unknown person is refused, never guessed.

"Slug" is the last part of a profile link: in
https://www.linkedin.com/in/rowan-ashdown/ the slug is `rowan-ashdown`. It survives
a name change, it is never reused, and it does not pick up decoration, which is why
it is the strongest key most people already have.

There is deliberately NO fuzzy matching here. A wrong merge is worse than a miss: a
miss shows up as a skip you can see, while a merge silently poisons one person's
history with another's and there is no way back. Near-matches belong in a review
pile, not in a join.

Read-only. This module never writes to your records.

Use:
    import identity
    pid = identity.resolve("https://www.linkedin.com/in/rowan-ashdown/")
    ids = identity.identifiers_for(pid)     # every identifier they answer to

CLI:
    python _engine/identity.py stats                 # a summary of your records
    python _engine/identity.py who "<identifier>"    # resolve one identifier
    python _engine/identity.py collisions            # names that are ambiguous, for review
"""

import json
import os
import re
import sys
import unicodedata
from pathlib import Path

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

_FRONT = re.compile(r"^\ufeff?---\s*\n(.*?)\n---", re.S)
_URL_IN = re.compile(r"(?:https?://)?(?:[\w-]+\.)?linkedin\.com/in/([^/?#\s\"']+)", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

DEFAULT_FOLDERS = ["People", "_staging"]


def vault_root():
    """Where your CRM lives.

    The engine is installed inside the CRM folder, so the folder above this file is
    the CRM itself. Setting OUTLIERS_CRM_VAULT overrides that, which is what the
    tests use so they never touch your real records.
    """
    env = os.environ.get("OUTLIERS_CRM_VAULT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def scan_folders(root):
    cfg = Path(root) / "_layers" / "config.json"
    if cfg.exists():
        try:
            got = json.loads(cfg.read_text(encoding="utf-8")).get("scan_folders")
            if got:
                return list(got)
        except (ValueError, OSError):
            pass
    return list(DEFAULT_FOLDERS)


# --------------------------------------------------------------------------- keys

def slug(value):
    """The canonical slug from any spelling of a profile link, else "".

    Handles: with or without https, any regional prefix (uk. / www. / none), a
    trailing slash, tracking rubbish on the end, and any casing. The result is
    lowercased because the platform treats it as case-insensitive.
    """
    if not value:
        return ""
    m = _URL_IN.search(str(value))
    if not m:
        return ""
    return m.group(1).strip().rstrip("/").lower()


def norm_name(value):
    """A display name reduced to a comparison key, or "".

    Normalises accents so that two ways of writing the same accented letter agree,
    strips leading decoration (a status symbol, a quote, a bullet), collapses runs of
    spaces, lowercases. Only LEADING decoration is removed, never a letter, so
    accented and non-Latin names survive intact.
    """
    if not value:
        return ""
    s = unicodedata.normalize("NFKC", str(value)).strip()
    s = re.sub(r"^\W+", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def norm_email(value):
    if not value:
        return ""
    m = _EMAIL.search(str(value))
    return m.group(0).strip().lower() if m else ""


def norm_phone(value):
    """Digits only, and only if there are enough of them to be a phone number.

    Country codes and spacing vary by who typed it, so the last nine digits are the
    part that stays the same. Anything shorter is too weak to be a key and is
    refused rather than guessed at.
    """
    if not value:
        return ""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 9:
        return ""
    return digits[-9:]


def listify(value):
    """A frontmatter list, however it was written: [a, b] or a, b or a single item."""
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    s = str(value).strip().strip("[]")
    return [p.strip().strip("'\"") for p in s.split(",") if p.strip().strip("'\"")]


def front_matter(text):
    """A deliberately small frontmatter reader: `key: value` at the top level.

    Tolerates a byte-order mark, quoted values, and both list styles. It is not a
    full YAML parser and does not pretend to be one; it reads the handful of
    identity fields this module needs and ignores the rest.
    """
    m = _FRONT.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if not line or line[:1] in (" ", "\t", "#", "-"):
            continue
        k, sep, v = line.partition(":")
        if not sep:
            continue
        v = v.strip().strip('"').strip("'").strip()
        if v:
            out[k.strip().lower()] = v
    return out


# ------------------------------------------------------------------- union-find
# The same human arrives as a profile link on one record, an email address on
# another and a bare name on a third. Grouping by "any shared strong key" is what
# joins them, and this is the smallest correct way to do that.

def _find(parent, x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent, a, b):
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[rb] = ra


# --------------------------------------------------------------------------- index

def build_index(vault=None):
    """Read your records and return the identity index.

    Returns a dict with "people" (id -> record), the three strong-key lookups,
    "by_name", and "ambiguous_names" -- the names that belong to more than one
    person and are therefore refused.
    """
    root = Path(vault) if vault else vault_root()
    raw = []

    for rel in scan_folders(root):
        folder = root / rel
        if not folder.exists():
            continue
        for f in sorted(folder.rglob("*.md")):
            text = f.read_text(encoding="utf-8", errors="replace")[:4000]
            fm = front_matter(text)

            slugs, emails, phones = set(), set(), set()

            s = slug(fm.get("linkedin-url") or fm.get("linkedin") or fm.get("profile-url") or "")
            if not s:
                s = slug(text[:2000])
            if s:
                slugs.add(s)
            e = norm_email(fm.get("email") or "")
            if e:
                emails.add(e)
            p = norm_phone(fm.get("phone") or "")
            if p:
                phones.add(p)

            display = fm.get("name") or f.stem
            names = {n for n in (norm_name(f.stem), norm_name(display)) if n}

            for a in listify(fm.get("aliases")):
                a_s, a_e, a_p = slug(a), norm_email(a), norm_phone(a)
                if a_s:
                    slugs.add(a_s)
                elif a_e:
                    emails.add(a_e)
                elif a_p:
                    phones.add(a_p)
                else:
                    n = norm_name(a)
                    if n:
                        names.add(n)

            if not (slugs or emails or phones or names):
                continue
            raw.append({
                "file": str(f.relative_to(root)).replace("\\", "/"),
                "folder": rel,
                "slugs": slugs, "emails": emails, "phones": phones, "names": names,
                "primary_slug": s,
            })

    # ---- group records that share any strong key ------------------------------
    parent = {i: i for i in range(len(raw))}
    owner = {}
    for i, r in enumerate(raw):
        for key in ([("slug", x) for x in r["slugs"]]
                    + [("email", x) for x in r["emails"]]
                    + [("phone", x) for x in r["phones"]]):
            if key in owner:
                _union(parent, owner[key], i)
            else:
                owner[key] = i

    groups = {}
    for i in range(len(raw)):
        groups.setdefault(_find(parent, i), []).append(i)

    # ---- fold a record with no strong key into its person ---------------------
    # A note carrying only a name is usually not a separate human. It is the same
    # person written down by something that never had the strong identifier. Left
    # alone it shadows the keyed record, makes the shared name ambiguous, and blocks
    # resolution for BOTH. The merge is only safe when the name matches exactly one
    # keyed person; one-to-many stays split and goes to review.
    def has_key(idxs):
        return any(raw[i]["slugs"] or raw[i]["emails"] or raw[i]["phones"] for i in idxs)

    keyed_by_name = {}
    for root_i, idxs in groups.items():
        if has_key(idxs):
            for i in idxs:
                for n in raw[i]["names"]:
                    keyed_by_name.setdefault(n, set()).add(root_i)

    for root_i in list(groups):
        idxs = groups.get(root_i) or []
        if has_key(idxs):
            continue
        owners = set()
        for i in idxs:
            for n in raw[i]["names"]:
                owners |= keyed_by_name.get(n, set())
        if len(owners) != 1:
            continue                       # 0 = genuinely keyless; more than 1 = ambiguous
        target = next(iter(owners))
        groups[target].extend(idxs)
        del groups[root_i]

    # ---- build the person records ---------------------------------------------
    people, by_slug, by_email, by_phone = {}, {}, {}, {}
    name_owners = {}

    for root_i, idxs in groups.items():
        slugs, emails, phones, names, files, folders = set(), set(), set(), set(), [], set()
        primary = ""
        for i in sorted(idxs):
            r = raw[i]
            slugs |= r["slugs"]
            emails |= r["emails"]
            phones |= r["phones"]
            names |= r["names"]
            files.append(r["file"])
            folders.add(r["folder"])
            if r["primary_slug"] and not primary:
                primary = r["primary_slug"]

        if not primary and slugs:
            primary = sorted(slugs)[0]
        if primary:
            pid = primary
        elif emails:
            pid = "email:" + sorted(emails)[0]
        elif phones:
            pid = "phone:" + sorted(phones)[0]
        elif names:
            pid = "name:" + sorted(names)[0]
        else:
            continue

        people[pid] = {
            "id": pid, "slug": primary, "slugs": slugs, "emails": emails,
            "phones": phones, "names": names, "files": files, "folders": folders,
        }
        for s in slugs:
            by_slug[s] = pid
        for e in emails:
            by_email[e] = pid
        for p in phones:
            by_phone[p] = pid
        for n in names:
            name_owners.setdefault(n, set()).add(pid)

    by_name = {n: next(iter(o)) for n, o in name_owners.items() if len(o) == 1}
    ambiguous = {n for n, o in name_owners.items() if len(o) > 1}

    return {"people": people, "by_slug": by_slug, "by_email": by_email,
            "by_phone": by_phone, "by_name": by_name,
            "ambiguous_names": ambiguous, "root": str(root)}


_CACHE = {}


def _index(index=None, vault=None):
    if index is not None:
        return index
    key = str(vault or vault_root())
    if key not in _CACHE:
        _CACHE[key] = build_index(vault)
    return _CACHE[key]


def forget():
    """Drop the cached index. Call this after your records change."""
    _CACHE.clear()


# --------------------------------------------------------------------------- api

def resolve(*identifiers, **kw):
    """Return the person id for any identifier(s) you happen to hold, or None.

    Strong keys first, then a full display name, but only when that name belongs to
    exactly one person. Ambiguous or unknown input returns None. This function never
    guesses, because a wrong merge is silent and permanent while a miss is visible.
    """
    idx = _index(kw.get("index"), kw.get("vault"))
    for ident in identifiers:
        if not ident:
            continue
        raw = str(ident)

        s = slug(raw)
        if s and s in idx["by_slug"]:
            return idx["by_slug"][s]

        e = norm_email(raw)
        if e and e in idx["by_email"]:
            return idx["by_email"][e]

        p = norm_phone(raw)
        if p and p in idx["by_phone"]:
            return idx["by_phone"][p]

        n = norm_name(raw)
        if n:
            if n in idx["ambiguous_names"]:
                continue                    # known to be two people: refuse
            if n in idx["by_name"]:
                return idx["by_name"][n]
    return None


def identifiers_for(pid, **kw):
    """Every identifier this person answers to: profile links, slugs, names,
    email addresses, phone numbers.

    Callers pass the whole set to anything that matches on what it is given. That is
    how a caller holding only a profile link stops sailing past a hold that was
    recorded under a name.
    """
    if not pid:
        return set()
    idx = _index(kw.get("index"), kw.get("vault"))
    rec = idx["people"].get(pid)
    if not rec:
        return set()
    out = set(rec["names"]) | set(rec["emails"]) | set(rec["phones"]) | set(rec["slugs"])
    for s in rec["slugs"]:
        out.add("https://www.linkedin.com/in/%s" % s)
    return {o for o in out if o}


def record(pid, **kw):
    """The full index record, with sets rendered as sorted lists."""
    idx = _index(kw.get("index"), kw.get("vault"))
    r = idx["people"].get(pid)
    if not r:
        return None
    return {k: (sorted(v) if isinstance(v, set) else v) for k, v in r.items()}


def duplicates(**kw):
    """People held in more than one file. Under the one-person-one-file rule this
    list should be empty; anything on it is a merge waiting to be done by hand."""
    idx = _index(kw.get("index"), kw.get("vault"))
    return {pid: r["files"] for pid, r in idx["people"].items() if len(r["files"]) > 1}


# --------------------------------------------------------------------------- cli

def _stats(idx):
    ppl = idx["people"]
    keyed = sum(1 for r in ppl.values() if r["slugs"] or r["emails"] or r["phones"])
    multi = sum(1 for r in ppl.values() if len(r["files"]) > 1)
    print("records in       %s" % idx["root"])
    print("people           %d" % len(ppl))
    print("  with a strong key  %d  (%.0f%%)"
          % (keyed, 100.0 * keyed / max(len(ppl), 1)))
    print("  name only          %d  (a name is not a key; these are fragile)"
          % (len(ppl) - keyed))
    print("  in more than one file  %d" % multi)
    print("ambiguous names  %d  (refused by resolve; they need review)"
          % len(idx["ambiguous_names"]))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "stats"
    idx = _index()
    if cmd == "stats":
        _stats(idx)
    elif cmd == "who" and len(argv) > 2:
        pid = resolve(argv[2], index=idx)
        if not pid:
            print("unresolved: %r" % argv[2])
            return 1
        print(json.dumps(record(pid, index=idx), indent=2, ensure_ascii=False))
    elif cmd == "collisions":
        amb = sorted(idx["ambiguous_names"])
        print("%d ambiguous name(s). resolve() refuses these:" % len(amb))
        for n in amb[:60]:
            print("  %s" % n)
        if len(amb) > 60:
            print("  ... and %d more" % (len(amb) - 60))
    elif cmd == "duplicates":
        dupes = duplicates(index=idx)
        print("%d person/people held in more than one file:" % len(dupes))
        for pid, files in sorted(dupes.items()):
            print("  %s" % pid)
            for f in files:
                print("      %s" % f)
    else:
        print(__doc__.replace("    python _engine/identity.py", "    python " + _typed("identity.py"))
              .replace("    python ", "    %s " % PY))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
