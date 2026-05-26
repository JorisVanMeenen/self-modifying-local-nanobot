"""Tests for Dream driven through AgentLoop._process_system_message."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.skills import BUILTIN_SKILLS_DIR
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


def _provider(default_model: str, max_tokens: int = 123) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.generation = SimpleNamespace(
        max_tokens=max_tokens, temperature=0.1, reasoning_effort=None
    )
    return provider


@pytest.fixture
def store(tmp_path):
    from nanobot.agent.memory import MemoryStore

    s = MemoryStore(tmp_path)
    s.write_soul("# Soul\n- Helpful")
    s.write_user("# User\n- Developer")
    s.write_memory("# Memory\n- Project X active")
    return s


@pytest.fixture
def mock_provider():
    return _provider("test-model")


@pytest.fixture
def mock_runner():
    return MagicMock()


@pytest.fixture
def loop(tmp_path, mock_provider, mock_runner):
    loop = AgentLoop(
        bus=MessageBus(),
        provider=mock_provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=1000,
    )
    loop.dream._runner = mock_runner
    return loop


def _make_run_result(
    stop_reason="completed",
    final_content=None,
    tool_events=None,
    usage=None,
):
    return AgentRunResult(
        final_content=final_content or stop_reason,
        stop_reason=stop_reason,
        messages=[],
        tools_used=[],
        usage={},
        tool_events=tool_events or [],
    )


class TestDreamAgentLoopIntegration:
    async def test_processes_full_backlog(self, loop, mock_runner, store):
        """All backlog entries should be processed and cursor advanced."""
        for i in range(6):
            store.append_history(f"event {i}")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        assert store.get_last_dream_cursor() == 6

    async def test_goal_tools_registered(self, loop):
        """Dream tool registry should include long_task and complete_goal."""
        names = loop.dream._tools.tool_names
        assert "long_task" in names
        assert "complete_goal" in names

    async def test_noop_when_no_unprocessed_history(self, loop, mock_runner):
        """Dream should not call runner when there's nothing to process."""
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        result = await loop._process_system_message(msg)
        assert result is None
        mock_runner.run.assert_not_called()

    async def test_calls_runner_for_unprocessed_entries(self, loop, mock_runner, store):
        """Dream should call AgentRunner when there are unprocessed history entries."""
        store.append_history("User prefers dark mode")
        mock_runner.run = AsyncMock(
            return_value=_make_run_result(
                tool_events=[
                    {"name": "edit_file", "status": "ok", "detail": "memory/MEMORY.md"}
                ],
            )
        )
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        mock_runner.run.assert_called_once()
        spec = mock_runner.run.call_args[0][0]
        assert spec.max_iterations == 10
        assert spec.fail_on_tool_error is False

    async def test_advances_dream_cursor(self, loop, mock_runner, store):
        """Dream should advance the cursor after processing."""
        store.append_history("event 1")
        store.append_history("event 2")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        assert store.get_last_dream_cursor() == 2

    async def test_compacts_processed_history(self, loop, mock_runner, store):
        """Dream should compact history after processing."""
        store.append_history("event 1")
        store.append_history("event 2")
        store.append_history("event 3")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert all(e["cursor"] > 0 for e in entries)

    async def test_processes_full_backlog_in_one_call(self, loop, mock_runner, store):
        """Full backlog should be processed in a single Dream run."""
        for i in range(12):
            store.append_history(f"event {i}")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        assert store.get_last_dream_cursor() == 12
        assert mock_runner.run.call_count == 1

    async def test_single_git_commit_for_multi_batch(self, loop, mock_runner, store):
        """Multi-batch run should collapse into exactly one git commit."""
        store.git.init()
        store.git.auto_commit("initial")
        for i in range(12):
            store.append_history(f"event {i}")
        mock_runner.run = AsyncMock(
            return_value=_make_run_result(
                tool_events=[
                    {"name": "edit_file", "status": "ok", "detail": "memory/MEMORY.md"}
                ],
            )
        )
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        commits = store.git.log()
        dream_commits = [c for c in commits if c.message.startswith("dream:")]
        assert len(dream_commits) == 1

    async def test_system_prompt_cached_within_batch(self, loop, mock_runner, store):
        """System prompt should be cached within a single _process_dream_batch call."""
        for i in range(6):
            store.append_history(f"event {i}")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        session = loop.sessions.get_or_create("system:dream")
        await loop._process_dream_batch(session, msg)
        assert mock_runner.run.call_count == 1
        first_prompt = mock_runner.run.call_args_list[0][0][0].initial_messages[0]["content"]
        # Calling _process_dream_batch again with new backlog reuses cached prompt
        store.append_history("another event")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        await loop._process_dream_batch(session, msg)
        assert mock_runner.run.call_count == 1
        second_prompt = mock_runner.run.call_args_list[0][0][0].initial_messages[0]["content"]
        assert second_prompt is first_prompt

    async def test_noop_when_empty_backlog(self, loop, mock_runner, store):
        """Empty backlog should not advance cursor or create a commit."""
        store.git.init()
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        assert store.get_last_dream_cursor() == 0
        commits = store.git.log()
        assert len([c for c in commits if c.message.startswith("dream:")]) == 0

    async def test_notifies_incomplete_on_max_iterations(self, loop, mock_runner, store):
        """When Dream hits max_iterations, user should get an incomplete notification."""
        store.append_history("event one")
        mock_runner.run = AsyncMock(
            return_value=_make_run_result(stop_reason="max_iterations")
        )
        msg = InboundMessage(
            channel="system",
            sender_id="dream",
            chat_id="dream",
            content="",
            metadata={"trigger_channel": "cli", "trigger_chat_id": "user1"},
        )
        loop.bus.publish_outbound = AsyncMock()
        await loop._process_system_message(msg)
        loop.bus.publish_outbound.assert_awaited_once()
        outbound = loop.bus.publish_outbound.await_args[0][0]
        assert "incomplete" in outbound.content
        assert store.get_last_dream_cursor() == 0

    async def test_notifies_incomplete_on_exception(self, loop, mock_runner, store):
        """When Dream runner raises, user should get an incomplete notification."""
        store.append_history("event one")
        mock_runner.run = AsyncMock(side_effect=RuntimeError("LLM error"))
        msg = InboundMessage(
            channel="system",
            sender_id="dream",
            chat_id="dream",
            content="",
            metadata={"trigger_channel": "cli", "trigger_chat_id": "user1"},
        )
        loop.bus.publish_outbound = AsyncMock()
        await loop._process_system_message(msg)
        loop.bus.publish_outbound.assert_awaited_once()
        outbound = loop.bus.publish_outbound.await_args[0][0]
        assert "incomplete" in outbound.content
        assert store.get_last_dream_cursor() == 0

    async def test_notifies_completed_on_success(self, loop, mock_runner, store):
        """When Dream succeeds, user should get a completed notification."""
        store.append_history("event one")
        mock_runner.run = AsyncMock(
            return_value=_make_run_result(
                tool_events=[
                    {"name": "edit_file", "status": "ok", "detail": "memory/MEMORY.md"}
                ],
            )
        )
        msg = InboundMessage(
            channel="system",
            sender_id="dream",
            chat_id="dream",
            content="",
            metadata={"trigger_channel": "cli", "trigger_chat_id": "user1"},
        )
        loop.bus.publish_outbound = AsyncMock()
        await loop._process_system_message(msg)
        loop.bus.publish_outbound.assert_awaited_once()
        outbound = loop.bus.publish_outbound.await_args[0][0]
        assert "completed" in outbound.content
        assert "1 change" in outbound.content


class TestDreamPrompt:
    async def test_prompt_contains_mece_rules(self, loop, mock_runner, store):
        store.append_history("some event")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        spec = mock_runner.run.call_args[0][0]
        system_prompt = spec.initial_messages[0]["content"]
        assert "Do NOT guess paths" in system_prompt
        assert "SOUL.md" in system_prompt
        assert "USER.md" in system_prompt
        assert "MEMORY.md" in system_prompt

    async def test_skill_phase_uses_builtin_skill_creator_path(self, loop, mock_runner, store):
        store.append_history("Repeated workflow one")
        store.append_history("Repeated workflow two")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        spec = mock_runner.run.call_args[0][0]
        system_prompt = spec.initial_messages[0]["content"]
        expected = str(BUILTIN_SKILLS_DIR / "skill-creator" / "SKILL.md")
        assert expected in system_prompt


class TestDreamPromptCaps:
    async def test_references_memory_file_size(self, loop, mock_runner, store):
        store.write_memory("M" * (loop.dream._MEMORY_FILE_MAX_CHARS * 5))
        store.append_history("some event")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        spec = mock_runner.run.call_args[0][0]
        user_msg = spec.initial_messages[1]["content"]
        assert "## Memory Files (read before editing)" in user_msg
        assert "80000 chars" in user_msg

    async def test_caps_huge_history_entry(self, loop, mock_runner, store):
        store.history_file.write_text(
            json.dumps(
                {
                    "cursor": 1,
                    "timestamp": "2026-04-01 10:00",
                    "content": "H" * (loop.dream._HISTORY_ENTRY_PREVIEW_MAX_CHARS * 8),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        spec = mock_runner.run.call_args[0][0]
        user_msg = spec.initial_messages[1]["content"]
        history_section = user_msg.split("## Conversation History\n")[1].split(
            "\n\n## Current Date"
        )[0]
        assert len(history_section) < loop.dream._HISTORY_ENTRY_PREVIEW_MAX_CHARS + 500


class TestDreamTools:
    def test_apply_patch_tool_registered(self, loop):
        tool = loop.dream._tools.get("apply_patch")
        assert tool is not None


class TestDreamCaps:
    def test_batch_size_default_is_5(self):
        from nanobot.config.schema import DreamConfig

        assert DreamConfig().max_batch_size == 5

    def test_memory_cap_is_16k(self, loop):
        assert loop.dream._MEMORY_FILE_MAX_CHARS == 16_000


class TestDreamSkipFiltering:
    async def test_skip_entries_removed_from_batch_file(self, loop, mock_runner, store):
        store.append_history("- [skip] greeting\n- [permanent] User prefers dark mode")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        session = loop.sessions.get_or_create("system:dream")
        await loop._process_dream_batch(session, msg)
        batch_file = store.workspace / ".dream_batch.jsonl"
        assert batch_file.exists()
        text = batch_file.read_text(encoding="utf-8")
        assert "User prefers dark mode" in text
        assert "[skip]" not in text
        assert "greeting" not in text


class TestDreamFileReferences:
    async def test_prompt_shows_file_references(self, loop, mock_runner, store):
        store.write_soul("# Soul\n- Helpful")
        store.write_user("# User\n- Developer")
        store.write_memory("# Memory\n- Project X active")
        store.append_history("some event")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        spec = mock_runner.run.call_args[0][0]
        user_msg = spec.initial_messages[1]["content"]
        assert "## Memory Files (read before editing)" in user_msg
        assert "MEMORY.md" in user_msg
        assert "SOUL.md" in user_msg
        assert "USER.md" in user_msg
        # Content should not be embedded
        assert "Project X active" not in user_msg
        assert "Helpful" not in user_msg
        assert "Developer" not in user_msg

    async def test_prompt_works_without_git(self, loop, mock_runner, store):
        store.append_history("some event")
        mock_runner.run = AsyncMock(return_value=_make_run_result())
        msg = InboundMessage(
            channel="system", sender_id="dream", chat_id="dream", content=""
        )
        await loop._process_system_message(msg)
        mock_runner.run.assert_called_once()
        spec = mock_runner.run.call_args[0][0]
        user_msg = spec.initial_messages[1]["content"]
        assert "## Memory Files (read before editing)" in user_msg


