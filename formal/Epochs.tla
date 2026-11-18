---------------------------- MODULE Epochs ----------------------------
(* An epoch barrier for a dependency-ordered Feldera pipeline.

   Independent connector queues hold changes and epoch markers. A normal
   step may consume any nonempty subset. A transaction commit consumes
   the buffered changes and markers in one step. Export rows may arrive in
   any order within the step, before its end signal.

   The driver can wait for the changes' completion before writing the
   marker, write both in a transaction, or push both without either guard.
   The relay can pass changes downstream at the marker row or at the end
   of its step. Publishing an epoch waits for every part in the graph. *)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS N, Feeds, MaxEpoch, Mode, At

Parts == 1..N
Producers == {p \in Parts : Feeds[p] # {}}
ASSUME \A p \in Parts : Feeds[p] \subseteq (p + 1)..N
ASSUME Mode \in {"wait", "txn", "nowait"} /\ At \in {"row", "step"}

VARIABLES
    e, cur, phase, manifest,  \* the driver: epoch, the part in hand, "run" or "published", last manifest
    stage,     \* the driver at part cur: "idle", "open" (transaction), "pushed", "marked", "committed"
    pending,   \* per part: changes the driver holds for it (base changes, and what relays handed on)
    dq, mq,    \* per part: changes and markers buffered in its input connectors
    txn,       \* per part: a transaction is open
    stream,    \* per part: its export stream, a sequence of [kind |-> "batch", rows |-> set] and [kind |-> "end"]
    buffer,    \* per part: the relay's buffer
    awaiting,  \* per part: the epoch of a marker read whose step has not closed yet (0: none)
    marked,    \* per part: the last epoch its relay handed on
    sent,      \* per part: every change it exported
    got        \* per part: what it received from relays, in order, as [d |-> change, at |-> epoch]
vars == <<e, cur, phase, manifest, stage, pending, dq, mq, txn, stream, buffer, awaiting, marked, sent, got>>

Base(p, ep) == [src |-> 0, ep |-> ep, id |-> <<p>>]
Out(p, d) == [src |-> p, ep |-> d.ep, id |-> <<d.src>> \o d.id]
SeqToSet(s) == {s[i] : i \in 1..Len(s)}
Count(q, d) == Cardinality({i \in 1..Len(got[q]) : got[q][i].d = d})

Touch(ep, touched) == [p \in Parts |-> IF p \in touched THEN {Base(p, ep)} ELSE {}]

Init ==
    /\ e = 1 /\ cur = 1 /\ phase = "run" /\ manifest = 0 /\ stage = "idle"
    /\ \E touched \in SUBSET Parts \ {{}} : pending = Touch(1, touched)
    /\ dq = [p \in Parts |-> {}] /\ mq = [p \in Parts |-> {}] /\ txn = [p \in Parts |-> FALSE]
    /\ stream = [p \in Parts |-> <<>>] /\ buffer = [p \in Parts |-> <<>>] /\ awaiting = [p \in Parts |-> 0]
    /\ marked = [p \in Parts |-> 0] /\ sent = [p \in Parts |-> {}] /\ got = [p \in Parts |-> <<>>]

-----------------------------------------------------------------------------
\* Feldera: one circuit step of part p over the changes D and markers M it takes from its queues.
StepOver(p, D, M) ==
    /\ dq' = [dq EXCEPT ![p] = @ \ D]
    /\ mq' = [mq EXCEPT ![p] = @ \ M]
    /\ IF p \in Producers
         THEN LET rows == {[kind |-> "delta", d |-> Out(p, d)] : d \in D}
                          \cup {[kind |-> "marker", ep |-> m] : m \in M}
              IN /\ stream' = [stream EXCEPT ![p] = @ \o <<[kind |-> "batch", rows |-> rows], [kind |-> "end"]>>]
                 /\ sent' = [sent EXCEPT ![p] = @ \cup {Out(p, d) : d \in D}]
         ELSE UNCHANGED <<stream, sent>>

\* A step in continuous mode: some of each queue, at least one record.
Step(p) ==
    /\ ~txn[p]
    /\ \E D \in SUBSET dq[p], M \in SUBSET mq[p] :
         /\ D # {} \/ M # {}
         /\ StepOver(p, D, M)
    /\ UNCHANGED <<e, cur, phase, manifest, stage, pending, txn, buffer, awaiting, marked, got>>

\* The relay hands its buffer on at epoch ep.
HandOn(p, ep) ==
    /\ pending' = [q \in Parts |-> IF q \in Feeds[p] THEN pending[q] \cup SeqToSet(buffer[p]) ELSE pending[q]]
    /\ got' = [q \in Parts |-> IF q \in Feeds[p]
                 THEN got[q] \o [i \in 1..Len(buffer[p]) |-> [d |-> buffer[p][i], at |-> ep]]
                 ELSE got[q]]
    /\ buffer' = [buffer EXCEPT ![p] = <<>>]
    /\ marked' = [marked EXCEPT ![p] = ep]

\* The relay of part p reads one row of the batch at the head of its stream (in any order), or the step chunk.
Relay(p) ==
    /\ stream[p] # <<>>
    /\ LET head == Head(stream[p]) IN
         IF head.kind = "end"
           THEN /\ stream' = [stream EXCEPT ![p] = Tail(@)]
                /\ IF awaiting[p] # 0
                     THEN HandOn(p, awaiting[p]) /\ awaiting' = [awaiting EXCEPT ![p] = 0]
                     ELSE UNCHANGED <<pending, got, buffer, marked, awaiting>>
         ELSE IF head.rows = {}
           THEN /\ stream' = [stream EXCEPT ![p] = Tail(@)]
                /\ UNCHANGED <<pending, got, buffer, marked, awaiting>>
         ELSE \E r \in head.rows :
                /\ stream' = [stream EXCEPT ![p][1].rows = @ \ {r}]
                /\ IF r.kind = "delta"
                     THEN /\ buffer' = [buffer EXCEPT ![p] = Append(@, r.d)]
                          /\ UNCHANGED <<pending, got, marked, awaiting>>
                   ELSE IF At = "row"
                     THEN HandOn(p, r.ep) /\ UNCHANGED awaiting
                   ELSE /\ awaiting' = [awaiting EXCEPT ![p] = r.ep]
                        /\ UNCHANGED <<pending, got, buffer, marked>>
    /\ UNCHANGED <<e, cur, phase, manifest, stage, dq, mq, txn, sent>>

-----------------------------------------------------------------------------
\* The driver handles the parts in order.
Driving == phase = "run" /\ cur <= N
Txn(p) == Mode = "txn" /\ p \in Producers

\* A part that got nothing in this epoch does nothing.
Skip ==
    /\ Driving /\ stage = "idle" /\ pending[cur] = {}
    /\ cur' = cur + 1
    /\ UNCHANGED <<e, phase, manifest, stage, pending, dq, mq, txn, stream, buffer, awaiting, marked, sent, got>>

Begin ==
    /\ Driving /\ stage = "idle" /\ pending[cur] # {} /\ Txn(cur)
    /\ txn' = [txn EXCEPT ![cur] = TRUE] /\ stage' = "open"
    /\ UNCHANGED <<e, cur, phase, manifest, pending, dq, mq, stream, buffer, awaiting, marked, sent, got>>

Push ==
    /\ Driving /\ pending[cur] # {}
    /\ IF Txn(cur) THEN stage = "open" ELSE stage = "idle"
    /\ dq' = [dq EXCEPT ![cur] = @ \cup pending[cur]]
    /\ pending' = [pending EXCEPT ![cur] = {}]
    /\ stage' = "pushed"
    /\ UNCHANGED <<e, cur, phase, manifest, mq, txn, stream, buffer, awaiting, marked, sent, got>>

\* "wait": the completion token of the push is complete, so every pushed change has been processed.
Mark ==
    /\ Driving /\ stage = "pushed" /\ cur \in Producers
    /\ Mode = "wait" => dq[cur] = {}
    /\ mq' = [mq EXCEPT ![cur] = @ \cup {e}]
    /\ stage' = "marked"
    /\ UNCHANGED <<e, cur, phase, manifest, pending, dq, txn, stream, buffer, awaiting, marked, sent, got>>

\* The commit is one step over everything buffered.
Commit ==
    /\ Driving /\ stage = "marked" /\ txn[cur]
    /\ StepOver(cur, dq[cur], mq[cur])
    /\ txn' = [txn EXCEPT ![cur] = FALSE] /\ stage' = "committed"
    /\ UNCHANGED <<e, cur, phase, manifest, pending, buffer, awaiting, marked, got>>

\* A producing part is done when its relay has handed epoch e on; any other part at its completion token.
Done ==
    /\ Driving
    /\ IF cur \in Producers
         THEN stage \in (IF Txn(cur) THEN {"committed"} ELSE {"marked"}) /\ marked[cur] = e
         ELSE stage = "pushed" /\ dq[cur] = {}
    /\ cur' = cur + 1 /\ stage' = "idle"
    /\ UNCHANGED <<e, phase, manifest, pending, dq, mq, txn, stream, buffer, awaiting, marked, sent, got>>

Publish ==
    /\ phase = "run" /\ cur > N
    /\ phase' = "published" /\ manifest' = e
    /\ UNCHANGED <<e, cur, stage, pending, dq, mq, txn, stream, buffer, awaiting, marked, sent, got>>

NextEpoch ==
    /\ phase = "published" /\ e < MaxEpoch
    /\ e' = e + 1 /\ cur' = 1 /\ phase' = "run"
    /\ \E touched \in SUBSET Parts \ {{}} :
         pending' = [p \in Parts |-> pending[p] \cup Touch(e + 1, touched)[p]]
    /\ UNCHANGED <<manifest, stage, dq, mq, txn, stream, buffer, awaiting, marked, sent, got>>

Finished == phase = "published" /\ e = MaxEpoch /\ UNCHANGED vars

Next ==
    \/ \E p \in Parts : Step(p) \/ Relay(p)
    \/ Skip \/ Begin \/ Push \/ Mark \/ Commit \/ Done \/ Publish \/ NextEpoch \/ Finished
Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
\* No reader sees a change without its epoch: each change is handed on at the marker of its own epoch.
InEpoch == \A q \in Parts : \A i \in 1..Len(got[q]) : got[q][i].at = got[q][i].d.ep
\* No reader sees an epoch without its change: once a relay hands epoch ep on, every change of an epoch
\* up to ep that the part has exported has reached each reader.
Complete == \A p \in Producers : \A d \in sent[p] : d.ep <= marked[p] => \A q \in Feeds[p] : Count(q, d) >= 1
\* The manifest of epoch e waits until every part has processed all it got.
Barrier == phase = "published" => \A p \in Parts : pending[p] = {} /\ dq[p] = {} /\ mq[p] = {}
\* Every exported change of an epoch up to e reaches each reader exactly once before that manifest.
ExactlyOnce ==
    phase = "published" => \A p \in Producers : \A q \in Feeds[p] : \A d \in sent[p] : d.ep <= e => Count(q, d) = 1
\* A reader sees the epochs in order.
Ordered == \A q \in Parts : \A i, j \in 1..Len(got[q]) : i < j => got[q][i].at <= got[q][j].at
\* Epochs only grow: the manifest and every relay's marker.
Monotone == [][manifest' >= manifest /\ \A p \in Parts : marked'[p] >= marked[p]]_vars
=============================================================================
