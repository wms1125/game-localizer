# Ren'Py renderer overlap fixture

This repository-owned fixture exercises the renderer text-overlap hard gate with
real Ren'Py `Render` trees. The reference and candidate projects are identical
except that the candidate moves the secondary label over the primary label.

The fixture is intentionally separate from `tests/golden/renpy`: it validates
runtime visual evidence, not extraction or build fingerprints.
