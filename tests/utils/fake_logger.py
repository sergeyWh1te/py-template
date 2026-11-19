from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Entry:
    level: str
    event: str
    fields: dict[str, object]


@dataclass(slots=True)
class FakeLogger:
    """Records log calls; satisfies app_template.utils.deps.Logger structurally."""

    entries: list[Entry] = field(default_factory=list)

    def debug(self, event: str, **kw: object) -> None:
        self.entries.append(Entry("debug", event, kw))

    def info(self, event: str, **kw: object) -> None:
        self.entries.append(Entry("info", event, kw))

    def warning(self, event: str, **kw: object) -> None:
        self.entries.append(Entry("warning", event, kw))

    def error(self, event: str, **kw: object) -> None:
        self.entries.append(Entry("error", event, kw))

    def levels(self) -> list[str]:
        out: list[str] = []
        for entry in self.entries:
            out.append(entry.level)
        return out
