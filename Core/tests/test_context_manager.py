from app.agent.context_manager import ContextManager, ContextSlice


def test_render_messages_keeps_history_and_current_user_input() -> None:
    context = ContextManager().build_slice(
        system_prompt="System",
        persona_examples=[],
        history=[
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Current question"},
        ],
        latest_input="Current question",
    )

    assert context.render_messages() == [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Current question"},
    ]


def test_render_messages_sends_latest_when_history_is_missing() -> None:
    context = ContextManager().build_slice(
        system_prompt="System",
        persona_examples=[],
        history=[],
        latest_input="Current question",
    )

    assert context.render_messages()[-1] == {"role": "user", "content": "Current question"}


def test_render_messages_keeps_latest_when_assistant_text_matches() -> None:
    context = ContextSlice(
        system_prompt="System",
        persona_examples=[],
        short_history=[{"role": "assistant", "content": "Same text"}],
        latest_input="Same text",
    )

    assert context.render_messages()[-1] == {"role": "user", "content": "Same text"}


def test_tool_history_does_not_create_invalid_tool_message() -> None:
    context = ContextManager().build_slice(
        system_prompt="System",
        persona_examples=[],
        history=[{"role": "tool", "content": "Result"}],
        latest_input="Continue",
    )

    assert {"role": "system", "content": "[TOOL_RESULT] Result"} in context.render_messages()
