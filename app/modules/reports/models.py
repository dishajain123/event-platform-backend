"""
No tables of its own — this module is pure read-side aggregation over
data owned by other modules (events, registrations, payments,
tickets). Kept as an explicit, intentionally-empty file (rather than
leaving it out entirely) so it's clear this is a deliberate design
choice, not an oversight — see repository.py for the actual queries.
"""