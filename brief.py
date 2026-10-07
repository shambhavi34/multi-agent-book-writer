"""A Brief is the only input to the system. It can describe ANY topic."""
from dataclasses import dataclass
import re


@dataclass
class Brief:
    title: str
    audience: str = "general readers"
    tone: str = "friendly, clear and encouraging, like a mentor explaining to a newcomer"
    chapters: int = 3
    min_words: int = 600
    max_words: int = 900
    notes: str = ""          # extra instructions, e.g. "focus on India", "prefer government sources"
    max_rounds: int = 3      # write -> review rounds per chapter

    def clamp(self):
        self.chapters = max(1, min(int(self.chapters), 8))
        self.min_words = max(150, int(self.min_words))
        self.max_words = max(self.min_words + 50, int(self.max_words))
        self.max_rounds = max(1, min(int(self.max_rounds), 5))
        return self

    def text(self):
        return (f"Title: {self.title}\nAudience: {self.audience}\nTone: {self.tone}\n"
                f"Length: {self.chapters} chapters, {self.min_words}-{self.max_words} words each\n"
                f"Notes: {self.notes or 'none'}")

    def slug(self):
        return re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:50] or "book"
