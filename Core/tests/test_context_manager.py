from app.agent.context_manager import ContextManager, ContextSlice


def test_model_context_includes_history_and_current_input_once() -> None:
    history = [
        {"role": "user", "content": "My name is Avis."},
        {"role": "assistant", "content": "Hello, Avis."},
        {"role": "user", "content": "What is my name?"},
    ]
    messages = ContextManager().build_slice(
        system_prompt="Reply naturally.",
        persona_examples=[],
        history=history,
        latest_input="What is my name?",
    ).render_messages()

    assert messages[1:] == history


def test_user_can_repeat_the_assistants_words() -> None:
    messages = ContextSlice(
        system_prompt="Reply naturally.",
        persona_examples=[],
        short_history=[{"role": "assistant", "content": "Hello"}],
        latest_input="Hello",
    ).render_messages()

    assert messages[-2:] == [
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Hello"},
    ]


def test_skipped_history_does_not_suppress_current_input() -> None:
    messages = ContextSlice(
        system_prompt="Reply naturally.",
        persona_examples=[],
        short_history=[{"role": "invalid", "content": "Hello"}],
        latest_input="Hello",
    ).render_messages()

    assert messages[-1] == {"role": "user", "content": "Hello"}


def test_custom_tool_results_do_not_require_native_tool_call_ids() -> None:
    messages = ContextSlice(
        system_prompt="Reply naturally.",
        persona_examples=[],
        short_history=[{"role": "tool", "content": "The current time is 12:30."}],
        latest_input="Use the latest tool result.",
    ).render_messages()

    assert len(messages) == 3
    assert messages[1]["role"] == "user"
    assert "The current time is 12:30." in messages[1]["content"]
