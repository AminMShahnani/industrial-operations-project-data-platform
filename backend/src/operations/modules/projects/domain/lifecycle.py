from dataclasses import dataclass

DEFAULT_STATES = ("planned", "active", "suspended", "closing", "closed", "archived")
DEFAULT_TRANSITIONS = (
    ("planned", "active"),
    ("planned", "archived"),
    ("active", "suspended"),
    ("suspended", "active"),
    ("active", "closing"),
    ("suspended", "closing"),
    ("closing", "closed"),
    ("closed", "archived"),
)


@dataclass(frozen=True)
class Lifecycle:
    states: tuple[str, ...] = DEFAULT_STATES
    transitions: tuple[tuple[str, str], ...] = DEFAULT_TRANSITIONS
    initial: str = "planned"
    terminal: tuple[str, ...] = ("archived",)

    def valid(self) -> bool:
        shape_valid = (
            1 <= len(self.states) <= 30
            and len(set(self.states)) == len(self.states)
            and self.initial in self.states
            and bool(self.terminal)
            and set(self.terminal) <= set(self.states)
            and len(self.transitions) <= 100
            and len(set(self.transitions)) == len(self.transitions)
            and all(
                a in self.states and b in self.states and a != b and a not in self.terminal
                for a, b in self.transitions
            )
        )
        if not shape_valid:
            return False
        forward = {self.initial}
        backward = set(self.terminal)
        for _ in self.states:
            forward.update(b for a, b in self.transitions if a in forward)
            backward.update(a for a, b in self.transitions if b in backward)
        return set(self.states) <= forward and set(self.states) <= backward

    def allows(self, before: str, after: str) -> bool:
        return self.valid() and (before, after) in self.transitions
