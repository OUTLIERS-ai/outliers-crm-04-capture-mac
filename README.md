**This is the Mac version.** On Windows, use [outliers-crm-04-capture](https://github.com/OUTLIERS-ai/outliers-crm-04-capture).

# Outliers CRM - Layer 4 - Capture

Layer 3 gave you a log of events and nobody writing it. If that somebody is you,
typing, you have reinvented admin, and admin is the thing that kills CRMs.

This layer fills the log from sources you already own.

## What a collector is

A small program that watches one place where things already happen and writes down
what it sees. That is the whole definition. It does not judge anybody, it does not
decide anything, and it does not send anything.

## Install it

From this folder:

    python3 install.py

It finds your CRM, asks two questions, installs the collectors, and then offers to
point one at a file so you can watch the log fill up. It reads the file without
writing anything first and tells you what it would do; nothing lands until you say
so.

If Layer 3 is not installed, this refuses and tells you so. Nothing is changed.

## What it needs beneath it

Layer 3, which needs Layer 2, which needs Layer 1.

- Layer 3 supplies the event log and the calculated fields.
- Layer 2 supplies the resolver. Every collector goes through it.

The installer checks `_layers/config.json` and stops politely if the layer below is
missing.

## Fetching is easy, joining is hard

This is the honest warning, and it is worth reading before you start.

Reading a file of messages is straightforward. Deciding that the "R Ashdown" in
your calendar, the profile link in your contacts export, and the address
rowan@ashdown.example are all one person is the entire difficulty, and it never goes
away. Every source names people differently. One human turns up as four different
identifiers. Two different humans share a name.

So every collector here goes through ONE resolver, the one Layer 2 installed. Not a
copy of it, not a version tuned for this particular source: the same one. Identity
gets decided in a single place. One place to fix means one place that can be wrong,
and when it is wrong it is wrong the same way everywhere, which is how you find it.

## What happens to somebody you do not already have

It writes a provisional record for them into `_staging/`, and their events attach to
that, so their history is readable from the first row.

What it will not do is decide that they are somebody you already have. A new record
is a new person until you say otherwise. A merge is a decision about which history is
right, and a wrong merge silently mixes two people together with no way back, so
that decision stays yours.

You then do one of three things with a staged record: add the missing identifier to
the person you already have and delete the staged file, move it into `People/`
because they are genuinely new, or leave it alone.

If a row does not even have enough in it to make a record from, the event is still
written with the raw identifiers and nobody named. Nothing is thrown away. A
collector that quietly discards what it cannot place makes the log look tidier and
makes every number taken from it wrong.

## Running it twice is safe

Every row a collector reads produces the same fingerprint every time, and a
fingerprint already in the log is skipped. So you can re-run an older export
alongside a newer one and only the new rows land.

That property matters more than speed. A collector that double-counts corrupts every
number derived from it, and the numbers are the point.

## The collectors

| Collector | What it reads |
|---|---|
| `messages` | A message export: one row per message sent or received. |
| `meetings` | A calendar or booking export: one row per meeting. |
| `connections` | A contacts or connections export: one row per person. |

They read `.csv` files, which is what almost every platform's download-your-data
button produces. Column names vary wildly between exports, so each collector looks
for several spellings of the columns it needs.

A row with no readable date, or with nothing that could identify anybody, is skipped
and counted. It is never given a made-up value.

**Message content is never read into the log.** What happened and when is the useful
part. Keeping copies of what was said is a liability nobody needs.

## Refresh tiers

What people write on a profile stops being true. They change job, the company gets
bought, the title changes. None of it announces itself, so the facts in your CRM rot
at a rate you cannot see.

You cannot re-check everybody, and re-checking nobody means the whole thing is out of
date within a year or two. So the work is rationed by tier, and the tier comes from
the event log rather than from anybody's opinion:

| Tier | Who is on it | Re-checked |
|---|---|---|
| active | people replying, meeting, booking | whenever you interact with them |
| warm | people you have messaged, waiting | on a schedule, monthly by default |
| cold | everyone else | on a slower schedule, quarterly by default |

Somebody you are actually talking to gets re-checked constantly and it costs nothing
extra, because you were looking at them anyway. The schedule only pays for the
people you are not talking to.

**A real event jumps the queue.** If somebody replies today they go to the front,
regardless of when their turn was due. A reply matters more than a rota, always. The
schedule exists to catch the people nothing is happening with; it must never hold up
somebody something IS happening with.

`refresh.py` produces the list. It never goes and looks at anything itself. Fetching
a page is a separate job, and one you may want to do by hand, with a tool, or not at
all. Keeping the two apart means the ranking can be trusted on its own and tested
without touching a network.

## What gets installed

| File | What it is for |
|---|---|
| `_engine/collect.py` | The collectors, and the runner. |
| `_engine/refresh.py` | Who to re-check, and in what order. |
| `_engine/safe_write.py` | Writes a file without ever damaging the old one. |
| `_engine/sources.json` | The sources you named. Yours to edit. |
| `_staging/` | People a collector found that you did not already have. |
| `_layers/Layer 4 - Capture.md` | What this layer did, for when you forget. |

The installer also adds one event type, `checked`, to your settings file, so the
re-check schedule has something to record. That is done by adding to the settings
file rather than by editing Layer 3's code, which is the point of having the
vocabulary in a settings file at all.

## Try it

In Terminal, from your CRM folder (if your CRM is not at `~/CRM`, put your own folder in the `cd` line): Put your own export file where `<file.csv>` is.

    cd ~/CRM
    python3 _engine/collect.py list
    python3 _engine/collect.py run connections <file.csv> --dry-run
    python3 _engine/collect.py run connections <file.csv>
    python3 _engine/collect.py all
    python3 _engine/refresh.py due
    python3 _engine/refresh.py tiers
    python3 _engine/refresh.py checked "a name"
    python3 _engine/ledger.py person "a name"
    python3 _engine/derive.py quiet 60

## Run the tests

From the folder you downloaded:

    cd ~/outliers-crm-04-capture-mac
    python3 tests/test_capture.py
    python3 tests/test_refresh_tiers.py
    python3 tests/test_atomic_writes.py

Each builds a scratch folder with invented people and invented export files in it,
and deletes it afterwards. They never touch your records.

The `crm/` folder in this repo also carries copies of the Layer 2 and Layer 3
modules, so the tests can run without the other repos being present. The installer
does not copy those across; if Layer 3 is installed, the versions already in your
CRM are the ones that run.

## Every file write is atomic

Opening a file for writing truncates it the instant the handle opens. If anything
goes wrong between then and the last byte, the file is left empty or half-written
and the previous contents are gone.

So nothing here opens an existing file for writing. Everything writes to a temporary
file, pushes it to disk, and swaps it into place in one operation. A reader sees
either the whole old file or the whole new one, never a fragment. There is a test
that deliberately kills a write halfway through and checks the original survived
byte for byte.

The event log is the one exception, and it is opened in append mode, which never
truncates.

## What it does not do

It does not go online. Every collector reads a file that is already on your machine.

It does not decide anything about anybody. Whether a person is worth your time,
whether a reply is warm or merely polite, what to say back: none of that is here.
That is Layer 5.

It does not merge people. When somebody is not already in your records it makes a
new provisional record rather than deciding they are somebody you have.

## Requirements

Python 3.8 or newer. Nothing else: no libraries to install, no account, no internet
connection. Runs on macOS and Linux.

This repo is made automatically from outliers-crm-04-capture@79cb0a1. To report a problem or suggest a change, use that repo, not this one.
