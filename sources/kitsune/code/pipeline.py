"""The reply pipeline: think -> feel -> speak -> animate, with per-user context management.

Independent of Vector, so it is easy to test and reuse.

Context: every user has their own conversation with Kitsune (SQLite). The model sees her main prompt, that user's
memory summary, and their uncompacted turns. Once a user has ``compact_after`` exchanges since the last compaction,
the older ones are summarised into their memory (keeping the last ``keep_recent`` verbatim). Compaction runs in the
background after she has answered, so it never slows a reply down.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional, Set

from .avatar import AvatarRenderer, split_lines
from .errors import ChatError, ProviderError, RenderError
from .moods import Mood
from .providers.emotion import EmotionDetector
from .providers.llm import ChatMessage, ChatModel
from .providers.speech import SpeechSynthesizer
from .storage import ConversationStore

log = logging.getLogger(__name__)

COMPACT_PROMPT = """You maintain Kitsune's long-term memory of one person she chats with.
Rewrite the memory below so it also covers the new conversation. Keep: the person's name and how they like to be
addressed, facts about them, their tastes (anime, manga, genres, characters), opinions, running jokes, promises
and recommendations Kitsune made, and anything unresolved. Drop small talk. Write in third person about "{name}",
as short notes, at most {words} words. Reply with the memory only.

Current memory:
{summary}

New conversation:
{transcript}"""


@dataclass
class Reply:
    text: str
    mood: Mood
    video: Optional[bytes] = None  # MP4, when speech and rendering succeeded
    warning: Optional[str] = None  # why there is no video, if one was expected


class ReplyPipeline:
    def __init__(
        self,
        *,
        persona: str,
        chat: ChatModel,
        emotion: EmotionDetector,
        store: ConversationStore,
        speech: Optional[SpeechSynthesizer] = None,
        avatar: Optional[AvatarRenderer] = None,
        compact_after: int = 8,
        keep_recent: int = 2,
        memory_words: int = 150,
        max_concurrent: int = 2,
        subtitles: bool = True,
    ) -> None:
        self.persona = persona
        self.chat = chat
        self.emotion = emotion
        self.store = store
        self.speech = speech
        self.avatar = avatar
        self.compact_after = max(1, compact_after)
        self.keep_recent = max(0, min(keep_recent, self.compact_after - 1))
        self.memory_words = memory_words
        self.subtitles = subtitles
        self._slots = asyncio.Semaphore(max_concurrent)
        self._user_locks: Dict[str, asyncio.Lock] = {}
        self._compacting: Set[str] = set()
        self._background: Set[asyncio.Task[None]] = set()

    @property
    def can_talk(self) -> bool:
        return self.speech is not None and self.avatar is not None

    def _lock(self, user_id: str) -> asyncio.Lock:
        return self._user_locks.setdefault(user_id, asyncio.Lock())

    # -- context ---------------------------------------------------------------------------------------------
    def system_prompt(self, user_name: str, memory: str = "", style: str = "") -> str:
        prompt = f"{self.persona}\n\n{style}\n\nYou are talking with {user_name}." if style else (
            f"{self.persona}\n\nYou are talking with {user_name}.")
        if memory:
            prompt += f"\n\nWhat you remember about {user_name} from earlier conversations:\n{memory}"
        return prompt

    def messages_for(self, user_id: str, user_name: str, text: str, style: str = "") -> List[ChatMessage]:
        ctx = self.store.context(user_id)
        return [
            {"role": "system", "content": self.system_prompt(user_name, ctx.summary, style)},
            *ctx.turns,
            {"role": "user", "content": text},
        ]

    async def think(
        self, user_id: str, user_name: str, text: str, *, channel: Optional[str] = None, style: str = ""
    ) -> str:
        """``style`` is extra instructions for this one answer (the module's text mode uses it)."""
        async with self._lock(user_id):  # one exchange at a time per user keeps their context in order
            reply = await self.chat.chat(self.messages_for(user_id, user_name, text, style))
            if reply:
                self.store.append(
                    user_id,
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": reply},
                    channel=channel,
                )
        if reply:
            self.schedule_compaction(user_id, user_name)
        return reply

    # -- compaction ------------------------------------------------------------------------------------------
    def needs_compaction(self, user_id: str) -> bool:
        return self.store.context(user_id).exchanges >= self.compact_after

    def schedule_compaction(self, user_id: str, user_name: str) -> None:
        if user_id in self._compacting or not self.needs_compaction(user_id):
            return
        task = asyncio.ensure_future(self.compact(user_id, user_name))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def compact(self, user_id: str, user_name: str) -> bool:
        """Summarise all but the last ``keep_recent`` exchanges into the user's memory."""
        if user_id in self._compacting:
            return False
        self._compacting.add(user_id)
        try:
            async with self._lock(user_id):
                turns = self.store.uncompacted(user_id)
                user_idx = [i for i, t in enumerate(turns) if t["role"] == "user"]
                if len(user_idx) < self.compact_after:
                    return False
                cut = user_idx[len(user_idx) - self.keep_recent] if self.keep_recent else len(turns)
                old = turns[:cut]
                if not old:
                    return False
                transcript = "\n".join(
                    f"{user_name if t['role'] == 'user' else 'Kitsune'}: {t['content']}" for t in old
                )
                prompt = COMPACT_PROMPT.format(
                    name=user_name,
                    words=self.memory_words,
                    summary=self.store.memory(user_id) or "(nothing yet)",
                    transcript=transcript,
                )
                try:
                    summary = await self.chat.chat([{"role": "user", "content": prompt}])
                except ChatError as e:
                    log.warning("couldn't compact %s's context: %s", user_id, e)
                    return False
                if not summary.strip():
                    return False
                n = self.store.compact(user_id, summary.strip(), old[-1]["id"])
                log.info("compacted %d messages of %s's context into memory", n, user_id)
                return True
        finally:
            self._compacting.discard(user_id)

    async def drain(self) -> None:
        """Wait for background compactions (tests, shutdown)."""
        if self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)

    # -- the reply -------------------------------------------------------------------------------------------
    async def reply(
        self,
        user_id: str,
        user_name: str,
        text: str,
        *,
        channel: Optional[str] = None,
        video: bool = True,
        on_mood: Optional[Callable[[Mood], Awaitable[None]]] = None,
    ) -> Reply:
        """Raises :class:`~kitsune.errors.ChatError` if the LLM fails; speech/render failures only drop the video."""
        async with self._slots:
            answer = await self.think(user_id, user_name, text, channel=channel)
            mood = await self.emotion.detect(answer) if answer else Mood.NEUTRAL
            result = Reply(answer, mood)
            if on_mood is not None and answer:
                try:
                    await on_mood(mood)  # e.g. react to the user's message before the video is ready
                except Exception as e:
                    log.debug("on_mood callback failed: %s", e)
            if not (answer and video and self.can_talk):
                return result
            try:
                result.video = await self.speak(answer, mood)
            except (ProviderError, RenderError) as e:
                log.warning("no video for this reply: %s", e)
                result.warning = str(e)
            return result

    async def do_tts(self, text: str) -> list:
        """Voice each line separately: the ``[{"text", "audio"}]`` segments Neku got from Inworld."""
        assert self.speech is not None
        lines = split_lines(text) or [text]
        audios = await asyncio.gather(*(self.speech.synthesize(line) for line in lines))
        return [{"text": line, "audio": audio} for line, audio in zip(lines, audios)]

    async def speak(self, text: str, mood: Mood) -> bytes:
        """Neku's ``avatar_waifu``: segments -> merged voice + SRT -> lip-sync -> video with subtitles."""
        assert self.avatar is not None
        segments = await self.do_tts(text)
        return await self.avatar.avatar_video_async(segments, mood, subtitles=self.subtitles)
