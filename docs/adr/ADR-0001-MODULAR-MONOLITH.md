# ADR-0001: Start as Modular Monolith
Status: Accepted

## Decision
Use a modular monolith with background workers for V1.

## Rationale
The domain is broad and still evolving. Transactional consistency and development speed outweigh premature independent deployment. Strong module boundaries and integration events preserve future extraction options.
