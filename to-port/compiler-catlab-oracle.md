Target-folder: compiler

Schema-operation oracle checks against Catlab (`compiler/rezono_compiler/operate`).
A planner must write a neutral test suite that migrates generated fact states forward and backward across schema operations and compares row multisets with the Catlab oracle.

The executable comparison in compiler/tests/catlab/compare.py covers class and arrow-slot
renames across three generated states. It checks every nonempty table in both directions,
including repeated identifiers and repeated links. The Julia comparison still needs a recorded
successful run with the committed Project.toml and Manifest.toml. The expected-red compiler
workflow test tracks that wiring. Other migration families have no comparison in this driver yet.
