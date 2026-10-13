from hub.chat_context import recent_context
from hub.db import Message


def message(identifier, role, content, label="CLOUD_ALLOWED"):
    return Message(id=identifier, conversation_id="fixture", role=role, content=content,
                   label=label, revision=1)


def test_unicode_tail_bound_and_omitted_private_audit():
    history = [
        message("private", "user", "Never send this", "LOCAL_ONLY"),
        message("goal", "user", "Create a concept"),
        message("answer", "assistant", "Änderung 日本語 " * 3000 + "End of partial answer"),
        message("latest", "user", "Continue"),
    ]
    frozen = recent_context(history)
    assert sum(len(p["content"].encode()) + 64 for p in frozen["parts"]) <= 16000
    assert frozen["roles"] == ["system", "user", "assistant", "user"]
    assert frozen["parts"][0]["label"] == "LOCAL_ONLY"
    assert frozen["parts"][-2]["content"].endswith("End of partial answer")
    assert frozen["context_window"]["omitted_message_ids"] == ["private"]
    assert frozen["context_window"]["truncated_messages"][0]["id"] == "answer"
    assert history[2].content.startswith("Änderung 日本語 ")


def test_latest_user_is_never_silently_cut_even_when_byte_budget_exceeded():
    latest = "界" * 16000
    frozen = recent_context([message("old", "user", "Earlier"),
                             message("latest", "user", latest)])
    assert frozen["parts"][0]["content"] == latest
    assert frozen["context_window"]["omitted_message_ids"] == ["old"]
    assert not frozen["context_window"]["truncated_messages"]
