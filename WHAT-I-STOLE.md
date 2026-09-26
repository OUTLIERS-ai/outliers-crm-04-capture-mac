# What this layer borrows

This layer is a small, plain version of a data pipeline. Almost every idea in it
comes from somewhere that had to do the same thing at a much larger scale, and it is
worth naming them honestly so you know where to read more.

## Extract, transform, load

The oldest name for what a collector does. ETL is the shape of every data-warehouse
pipeline since the 1970s: pull raw records out of a source system, reshape them into
the shape your system uses, and load them in.

The part worth copying is the discipline of keeping the three steps separate. Each
collector here does exactly one job: turn rows of one source into events. It does
not resolve identity (the resolver does), it does not decide what an event means
(the calculations do), and it does not decide what to do about it (that is a later
layer). When something is wrong you can tell which of those was wrong.

## Idempotency, and the idempotency key

Straight from message queues, payment APIs and distributed systems generally. An
operation is idempotent if doing it twice has the same effect as doing it once. The
usual way to get there is an idempotency key: a value derived from the content of
the request, which the receiver remembers, so a repeat is recognised and ignored.

That is exactly what the fingerprint on each row is. Stripe, and most payment
processors, use the same mechanism for the same reason: the alternative to
recognising a repeat is charging somebody twice.

A collector that double-counts corrupts every number derived from it, silently, and
you will not notice until the numbers matter.

## Extract-load, then transform, on immutable raw data

A more recent variant, and the reason unidentified rows are still written. The
principle from modern data engineering is: land the raw fact first, transform later.
If you filter at the door, the thing you filtered out is gone and you can never
reconsider.

So an event nobody can attribute is still recorded, with the identifiers it arrived
with. Later, when the resolver knows more, it is still there.

## Dead-letter queues

The `_staging/` folder is a dead-letter queue, from message-broker design. When a
message cannot be processed, it goes to a separate queue for a human to look at,
instead of being retried forever or discarded.

The key property is that failure is visible and reviewable rather than silent. A
system that quietly drops what it cannot handle looks healthier than one that shows
you a queue of problems, and is worse.

## Staging tables, and the medallion pattern

`_staging/` is also a staging table in the data-warehouse sense: data lands
somewhere provisional first, gets checked, and only then joins the trusted set. Some
people call this a bronze/silver/gold or medallion architecture. The idea is older
than the name.

## Single source of truth for identity

Master data management, in enterprise data terms. The problem it addresses is that
the same customer exists in five systems under five identifiers, and each system
decides for itself which is which.

The rule this layer follows is the one that field arrived at the hard way: identity
is resolved in one place, and everything else asks that place. Not because it is
tidier, but because a resolver used everywhere is wrong the same way everywhere,
which is what makes the fault findable. Five resolvers are wrong five different ways
and there is nothing to fix.

## Cache invalidation and time-to-live

The refresh tiers are a cache with a time-to-live, and the problem is the classic
one: your copy of a fact was correct when you took it and you have no way of knowing
when it stopped being correct.

The tiering is the same trade every cache makes. Re-check everything and you spend
all your effort on it. Re-check nothing and everything is stale. So you re-check by
how much it matters and how likely it is to have changed.

## Event-driven invalidation

"A real event jumps the queue" is push-based cache invalidation. The schedule is a
time-to-live; a reply is the source telling you it has changed. When you have the
signal, you do not wait for the timer, because the timer was only ever a guess about
when the signal might have happened.

## Atomic file replacement

Write to a temporary file, flush, then rename over the target. This is how every
careful Unix program has written a file since roughly forever, and it is why
`rename` is specified to be atomic. Python's `os.replace` provides the same
guarantee on Windows.

The failure it prevents is specific and it is worth understanding: opening a file
for writing truncates it immediately, before any new bytes are written. Everything
between that instant and the last byte is a window in which the old contents are
gone and the new ones are not there yet.

## Data minimisation

Not reading message content into the log is a data-protection principle, and it
appears in the UK and EU General Data Protection Regulation by that name: collect
what you need for the purpose and no more.

The practical version is simpler. Data you do not hold cannot leak, cannot be
requested, and cannot be got wrong. What happened and when is what the system
actually uses. Copies of what was said are a liability with no corresponding
benefit.
