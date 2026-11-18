------------------------------- MODULE Effect -------------------------------
EXTENDS Naturals, FiniteSets

CONSTANTS Workers, UseLock

(* One exact, retained plan hash. The provider accepts a second submit if sent.
   An idle worker also models a retry by a new process on the same plan. *)
VARIABLES claimed, phase, pc, submitted, created, live
vars == <<claimed, phase, pc, submitted, created, live>>

Init ==
    /\ claimed = FALSE
    /\ phase = "planned"
    /\ pc = [w \in Workers |-> "idle"]
    /\ submitted = {}
    /\ created = {}
    /\ live = {}

Claim(w) ==
    /\ pc[w] = "idle"
    /\ phase \in {"planned", "applying", "unknown"}
    /\ (~UseLock \/ ~claimed)
    /\ claimed' = TRUE
    /\ phase' = "applying"
    /\ pc' = [pc EXCEPT ![w] = "ready"]
    /\ UNCHANGED <<submitted, created, live>>

CrashBeforeSubmit(w) ==
    /\ pc[w] = "ready"
    /\ pc' = [pc EXCEPT ![w] = "stopped"]
    /\ phase' = IF phase = "applying" THEN "unknown" ELSE phase
    /\ UNCHANGED <<claimed, submitted, created, live>>

Submit(w, outcome) ==
    /\ pc[w] = "ready"
    /\ pc' = [pc EXCEPT ![w] = "sent"]
    /\ submitted' = submitted \cup {w}
    /\ created' = IF outcome = "created" THEN created \cup {w} ELSE created
    /\ live' = IF outcome = "created" THEN live \cup {w} ELSE live
    (* A create with a lost answer and a possible create without a resource
       both look unknown to the journal. Failed requires a definite rejection. *)
    /\ phase' = IF outcome = "refused" THEN "failed" ELSE "unknown"
    /\ UNCHANGED claimed

ObserveUncertain ==
    /\ phase \in {"applying", "unknown"}
    /\ phase' = "unknown"
    /\ UNCHANGED <<claimed, pc, submitted, created, live>>

ReconcilePresent ==
    /\ phase = "unknown"
    /\ live # {}
    /\ phase' = "applied"
    /\ UNCHANGED <<claimed, pc, submitted, created, live>>

ConfirmCleanup ==
    /\ phase = "applied"
    /\ phase' = "cleaned"
    /\ live' = {}
    /\ UNCHANGED <<claimed, pc, submitted, created>>

Next ==
    \/ \E w \in Workers : Claim(w) \/ CrashBeforeSubmit(w)
    \/ \E w \in Workers, outcome \in {"created", "unknown", "refused"} : Submit(w, outcome)
    \/ ObserveUncertain
    \/ ReconcilePresent
    \/ ConfirmCleanup

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ claimed \in BOOLEAN
    /\ phase \in {"planned", "applying", "unknown", "applied", "failed", "cleaned"}
    /\ pc \in [Workers -> {"idle", "ready", "sent", "stopped"}]
    /\ submitted \subseteq Workers
    /\ created \subseteq submitted
    /\ live \subseteq created

AtMostOneSubmit == Cardinality(submitted) <= 1
AtMostOneResource == Cardinality(created) <= 1
ClaimMatchesPhase == claimed = (phase # "planned")
ClaimNeverDrops == [][claimed => claimed']_vars
TerminalConsumesClaim ==
    phase \in {"applied", "failed", "cleaned"} =>
        /\ claimed
        /\ submitted # {}
        /\ \A w \in Workers : pc[w] # "ready"
EvidenceMatchesPhase ==
    /\ (phase = "applied" => live # {})
    /\ (phase \in {"planned", "applying", "failed", "cleaned"} => live = {})

=============================================================================
