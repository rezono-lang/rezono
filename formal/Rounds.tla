------------------------------- MODULE Rounds -------------------------------
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS MaxBatch, TrustSubmit, CombinedOnly

Runs == 1..2
Workers == 1..2
Cuts == 1..2
Protect == "protect"
Expose == "expose"
Effects == {Protect, Expose, "audit"}
Pins == [run : Runs, cut : Cuts]
NoPin == [run |-> 0, cut |-> 0]
NoRead == [pin |-> NoPin, present |-> {}]
NoBatch == [pin |-> NoPin, base |-> {}, members |-> {}]
Certificates == [pin : Pins \cup {NoPin}, base : SUBSET Effects, members : SUBSET Effects]

VARIABLES run, cut, available, actual, confirmed, chosen, pending, claims,
          submits, stopped, lost, readback, rejected, sweep, done, fixed

vars == <<run, cut, available, actual, confirmed, chosen, pending, claims,
          submits, stopped, lost, readback, rejected, sweep, done, fixed>>

Init ==
    /\ run = 1
    /\ cut = 1
    /\ available \in {Effects, Effects \ {Protect}}
    /\ actual = {}
    /\ confirmed = {}
    /\ chosen = NoBatch
    /\ pending = {}
    /\ claims = [effect \in Effects |-> 0]
    /\ submits = <<>>
    /\ stopped = {}
    /\ lost = {}
    /\ readback = NoRead
    /\ rejected = {}
    /\ sweep = "genesis"
    /\ done = {}
    /\ fixed = FALSE

Current == [run |-> run, cut |-> cut]
Valid(resources) == Expose \in resources => Protect \in resources
EveryPrefix(base, batch) == \A visible \in SUBSET batch : Valid(base \cup visible)
Eligible == {m \in available \ confirmed : claims[m] = 0}
Unresolved == {m \in Effects \ confirmed : claims[m] # 0}

Certified(batch) ==
    /\ batch \subseteq Eligible
    /\ 1 <= Cardinality(batch)
    /\ Cardinality(batch) <= MaxBatch
    /\ IF CombinedOnly THEN Valid(confirmed \cup batch) ELSE EveryPrefix(confirmed, batch)

Submitted(m) == \E i \in 1..Len(submits) : submits[i].effect = m

(* Each modeled member is one exact effect hash, independent of the run and cut. *)
Evaluate(batch) ==
    /\ sweep \in {"genesis", "closed"}
    /\ chosen = NoBatch
    /\ ~fixed
    /\ Certified(batch)
    /\ chosen' = [pin |-> Current, base |-> confirmed, members |-> batch]
    /\ pending' = batch
    /\ UNCHANGED <<run, cut, available, actual, confirmed, claims, submits, stopped, lost,
                   readback, rejected, sweep, done, fixed>>

Claim(w, m) ==
    /\ chosen.pin = Current
    /\ m \in pending
    /\ claims[m] = 0
    /\ w \notin stopped
    /\ claims' = [claims EXCEPT ![m] = w]
    /\ UNCHANGED <<run, cut, available, actual, confirmed, chosen, pending, submits,
                   stopped, lost, readback, rejected, sweep, done, fixed>>

SubmitOne(w, m, visible) ==
    /\ chosen.pin = Current
    /\ m \in pending
    /\ claims[m] = w
    /\ w \notin stopped
    /\ ~Submitted(m)
    /\ submits' = Append(submits, [effect |-> m, worker |-> w, claim |-> claims[m],
                                  at |-> Current, certificate |-> chosen])
    /\ actual' = IF visible THEN actual \cup {m} ELSE actual
    /\ done' = IF TrustSubmit THEN done \cup {m} ELSE done
    /\ UNCHANGED <<run, cut, available, confirmed, chosen, pending, claims, stopped,
                   lost, readback, rejected, sweep, fixed>>

Crash(w) ==
    /\ w \notin stopped
    /\ \E m \in Effects : claims[m] = w
    /\ stopped' = stopped \cup {w}
    /\ UNCHANGED <<run, cut, available, actual, confirmed, chosen, pending, claims, submits,
                   lost, readback, rejected, sweep, done, fixed>>

LoseReply(m) ==
    /\ Submitted(m)
    /\ m \notin lost
    /\ lost' = lost \cup {m}
    /\ UNCHANGED <<run, cut, available, actual, confirmed, chosen, pending, claims, submits,
                   stopped, readback, rejected, sweep, done, fixed>>

(* An environmental correction between cuts may remove a resource while preserving safety. *)
Correct(m) ==
    /\ cut = 2
    /\ sweep = "open"
    /\ readback = NoRead
    /\ m \in actual
    /\ Valid(actual \ {m})
    /\ actual' = actual \ {m}
    /\ UNCHANGED <<run, cut, available, confirmed, chosen, pending, claims, submits,
                   stopped, lost, readback, rejected, sweep, done, fixed>>

Observe(r, c) ==
    LET pin == [run |-> r, cut |-> c] IN
    /\ IF pin = Current
       THEN /\ readback = NoRead
            /\ readback' = [pin |-> pin, present |-> actual]
            /\ UNCHANGED rejected
       ELSE /\ pin \notin rejected
            /\ rejected' = rejected \cup {pin}
            /\ UNCHANGED readback
    /\ UNCHANGED <<run, cut, available, actual, confirmed, chosen, pending, claims, submits,
                   stopped, lost, sweep, done, fixed>>

CloseSweep ==
    /\ readback.pin = Current
    /\ sweep # "closed"
    /\ sweep' = "closed"
    /\ confirmed' = readback.present
    /\ UNCHANGED <<run, cut, available, actual, chosen, pending, claims, submits,
                   stopped, lost, readback, rejected, done, fixed>>

Reconcile ==
    /\ sweep = "closed"
    /\ readback.pin = Current
    /\ \/ done # confirmed
       \/ pending \cap confirmed # {}
    /\ done' = confirmed
    /\ pending' = pending \ confirmed
    /\ UNCHANGED <<run, cut, available, actual, confirmed, chosen, claims, submits,
                   stopped, lost, readback, rejected, sweep, fixed>>

NextRound(r) ==
    /\ cut = 1
    /\ chosen # NoBatch \/ fixed
    /\ run' = r
    /\ cut' = 2
    /\ confirmed' = {}
    /\ chosen' = NoBatch
    /\ pending' = {}
    /\ readback' = NoRead
    /\ sweep' = "open"
    /\ done' = {}
    /\ fixed' = FALSE
    /\ UNCHANGED <<available, actual, claims, submits, stopped, lost, rejected>>

Blocked ==
    /\ sweep = "closed"
    /\ readback.pin = Current
    /\ Expose \notin confirmed
    /\ pending = {}
    /\ Unresolved = {}
    /\ ~(\E batch \in SUBSET Effects : Certified(batch))

ConcludeFixedPoint ==
    /\ ~fixed
    /\ Blocked
    /\ fixed' = TRUE
    /\ UNCHANGED <<run, cut, available, actual, confirmed, chosen, pending, claims, submits,
                   stopped, lost, readback, rejected, sweep, done>>

Next ==
    \/ \E batch \in SUBSET Effects : Evaluate(batch)
    \/ \E w \in Workers, m \in Effects : Claim(w, m)
    \/ \E w \in Workers, m \in Effects, visible \in BOOLEAN : SubmitOne(w, m, visible)
    \/ \E w \in Workers : Crash(w)
    \/ \E m \in Effects : LoseReply(m) \/ Correct(m)
    \/ \E r \in Runs, c \in Cuts : Observe(r, c)
    \/ CloseSweep
    \/ Reconcile
    \/ \E r \in Runs : NextRound(r)
    \/ ConcludeFixedPoint

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ Current \in Pins
    /\ available \subseteq Effects
    /\ actual \subseteq Effects
    /\ confirmed \subseteq Effects
    /\ chosen \in Certificates
    /\ pending \subseteq chosen.members
    /\ claims \in [Effects -> Workers \cup {0}]
    /\ submits \in Seq([effect : Effects, worker : Workers, claim : Workers,
                        at : Pins, certificate : Certificates])
    /\ stopped \subseteq Workers
    /\ lost \subseteq Effects
    /\ readback \in [pin : Pins \cup {NoPin}, present : SUBSET Effects]
    /\ rejected \subseteq Pins
    /\ sweep \in {"genesis", "open", "closed"}
    /\ done \subseteq Effects
    /\ fixed \in BOOLEAN

EveryVisiblePrefixValid == Valid(actual)

OnlyCertifiedDispatch ==
    \A i \in 1..Len(submits) :
        LET submission == submits[i] IN
        /\ submission.effect \in submission.certificate.members
        /\ submission.at = submission.certificate.pin
        /\ submission.worker = submission.claim
        /\ EveryPrefix(submission.certificate.base, submission.certificate.members)

DoneHasCurrentMatchingObservation ==
    done # {} =>
        /\ sweep = "closed"
        /\ readback.pin = Current
        /\ done \subseteq readback.present

AtMostOneSubmitPerNonrepeatableHash ==
    \A m \in Effects : Cardinality({i \in 1..Len(submits) : submits[i].effect = m}) <= 1

NoFalseFixedPoint == fixed => Blocked

=============================================================================
