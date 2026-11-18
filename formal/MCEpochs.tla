------------------------------- MODULE MCEpochs -------------------------------
(* A three-part dependency graph. Part 1 feeds 2 and 3. Part 2 feeds 3. *)
EXTENDS Epochs

FeedsDiamond == <<{2, 3}, {3}, {}>>
=============================================================================
