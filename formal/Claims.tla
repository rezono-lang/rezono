------------------------------ MODULE Claims ------------------------------
EXTENDS Naturals

CONSTANTS MaxTick, MaxVersion, CheckOpenPR

(* One claim ref, one cleanup run in flight, and a bounded logical clock.
   The generation changes on renewal and reacquisition. Delete and OpenPR
   are serialized at the claim, so Delete can check the current PR state.
   Observe is only a candidate read. Confirm reads the ref after the delete. *)
VARIABLES now, generation, present, leaseUntil, openPR,
          observed, pending, removals, confirmed

vars == <<now, generation, present, leaseUntil, openPR,
          observed, pending, removals, confirmed>>

Init ==
    /\ now = 0 /\ generation = 0 /\ ~present /\ leaseUntil = 0 /\ ~openPR
    /\ observed = 0 /\ pending = 0 /\ removals = {} /\ confirmed = {}

Tick ==
    /\ now < MaxTick
    /\ now' = now + 1
    /\ UNCHANGED <<generation, present, leaseUntil, openPR, observed, pending, removals, confirmed>>

Acquire ==
    /\ ~present /\ ~openPR /\ generation < MaxVersion
    /\ present' /\ generation' = generation + 1 /\ leaseUntil' = now + 1
    /\ UNCHANGED <<now, openPR, observed, pending, removals, confirmed>>

Renew ==
    /\ present /\ generation < MaxVersion
    /\ generation' = generation + 1 /\ leaseUntil' = now + 1
    /\ UNCHANGED <<now, present, openPR, observed, pending, removals, confirmed>>

OpenPR ==
    /\ present /\ ~openPR
    /\ openPR'
    /\ UNCHANGED <<now, generation, present, leaseUntil, observed, pending, removals, confirmed>>

ClosePR ==
    /\ openPR
    /\ ~openPR'
    /\ UNCHANGED <<now, generation, present, leaseUntil, observed, pending, removals, confirmed>>

Observe ==
    /\ present /\ now >= leaseUntil /\ ~openPR /\ pending = 0
    /\ observed' = generation
    /\ UNCHANGED <<now, generation, present, leaseUntil, openPR, pending, removals, confirmed>>

Delete ==
    /\ present /\ observed = generation /\ pending = 0
    /\ now >= leaseUntil
    /\ (~CheckOpenPR \/ ~openPR)
    /\ ~present' /\ pending' = generation /\ observed' = 0
    /\ removals' = removals \cup {[version |-> generation, tick |-> now,
                                  expiry |-> leaseUntil, pr |-> openPR]}
    /\ UNCHANGED <<now, generation, leaseUntil, openPR, confirmed>>

Confirm ==
    /\ pending # 0 /\ generation = pending /\ ~present
    /\ confirmed' = confirmed \cup {pending}
    /\ pending' = 0
    /\ UNCHANGED <<now, generation, present, leaseUntil, openPR, observed, removals>>

DiscardConfirmation ==
    /\ pending # 0 /\ generation # pending
    /\ pending' = 0
    /\ UNCHANGED <<now, generation, present, leaseUntil, openPR, observed, removals, confirmed>>

Next == Tick \/ Acquire \/ Renew \/ OpenPR \/ ClosePR \/ Observe
        \/ Delete \/ Confirm \/ DiscardConfirmation

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ now \in 0..MaxTick /\ generation \in 0..MaxVersion /\ leaseUntil \in 0..(MaxTick + 1)
    /\ present \in BOOLEAN /\ openPR \in BOOLEAN
    /\ observed \in 0..generation /\ pending \in 0..generation
    /\ removals \subseteq [version: 1..MaxVersion, tick: 0..MaxTick,
                           expiry: 0..(MaxTick + 1), pr: BOOLEAN]
    /\ confirmed \subseteq 1..MaxVersion

SafeRemoval ==
    \A receipt \in removals : receipt.tick >= receipt.expiry /\ ~receipt.pr

ConfirmedRemoval ==
    confirmed \subseteq {receipt.version : receipt \in removals}

ConfirmationReadsAbsence ==
    [][(confirmed' # confirmed) => (pending = generation /\ ~present)]_vars
=============================================================================
