# Clean-Room Policy

HanEngine uses observer and implementer separation: an observer may record
high-level architecture facts, while an implementer creates original code from
that record without access to copied implementation expressions.

Allowed observations are behavior, public interfaces, data flow, and
high-level architecture. Copied expressions are forbidden, including source
code, pseudocode, scripts, binaries, models, UI assets, installer trees,
identifiers, comments, and other non-functional expression from restricted
material.

Implementation sources are official documentation and repository-owned
synthetic fixtures. Every pull request must declare its implementation
sources and any permitted observations it relies on.

The product does not support injection, hooks, process-memory access, or
access to protected resources. Such capabilities and their supporting assets
are prohibited from this repository.
