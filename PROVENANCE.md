# Provenance

`compliance/provenance.json` uses the `hanengine.provenance/v1` contract to
record project identity, license state, implementation-source categories, and
restricted reference material. The listed archive SHA-256 is evidence that
identifies a reviewed archive; it does not authorize inclusion or use of its
contents.

`compliance/third_party_components.json` uses the `hanengine.third-party/v1`
contract to record redistributed third-party components.

Run an audit with `python tools/check_compliance.py --json`. Run the release
gate with `python tools/check_compliance.py --release --json`. The root
license remains unresolved, so audit reports a warning and the release gate
intentionally fails until a root-license decision is made.
