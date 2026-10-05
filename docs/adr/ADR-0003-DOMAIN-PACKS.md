# ADR-0003: Industry/Customer Behavior via Domain Packs
Status: Accepted

## Decision
Core remains industry-neutral. Industry and customer semantics are delivered through versioned installable Domain Packs and organization overlays.

## Consequence
Core code must never contain conditions such as `if industry == oil_gas` for domain behavior. Generic extension interfaces are allowed; concrete content belongs in packs.
