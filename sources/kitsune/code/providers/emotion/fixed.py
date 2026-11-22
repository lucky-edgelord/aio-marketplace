from ...moods import Mood


class FixedEmotion:
    """Always the same mood (used when no emotion model is installed, and in tests)."""

    def __init__(self, mood: Mood = Mood.NEUTRAL) -> None:
        self.mood = mood

    async def detect(self, text: str) -> Mood:
        return self.mood
