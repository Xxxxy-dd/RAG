from rag.workers import persist_worker


def test_process_once_parses_bytes_fields_and_acks(monkeypatch) -> None:
    acked = []

    monkeypatch.setattr(persist_worker.PersistWorker, "_claim_and_process_pending", lambda self: 0)
    monkeypatch.setattr(persist_worker, "is_already_processed", lambda key: False)
    monkeypatch.setattr(persist_worker, "mark_processed", lambda *args, **kwargs: None)
    monkeypatch.setattr(persist_worker, "clear_retry", lambda *args, **kwargs: None)
    monkeypatch.setattr(persist_worker, "increment_retry", lambda *args, **kwargs: 1)
    monkeypatch.setattr(persist_worker, "send_to_dead_letter", lambda **kwargs: "dlq-1")
    monkeypatch.setattr(
        persist_worker,
        "read_qa_turn_events",
        lambda **kwargs: [
            (
                "rag:events",
                [
                    (
                        b"1778935000000-0",
                        {
                            b"event_type": b"qa_turn",
                            b"session_id": b"sess-1",
                            b"question": b"Q",
                            b"answer": b"A",
                            b"conversation_title": b"t",
                            b"user_message_id": b"u1",
                            b"assistant_message_id": b"a1",
                            b"user_metadata": b"{}",
                            b"assistant_metadata": b"{}",
                            b"snapshot": b"[]",
                        },
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(persist_worker, "record_chat_turn", lambda **kwargs: True)
    monkeypatch.setattr(
        persist_worker,
        "ack_qa_turn_event",
        lambda event_id, **kwargs: acked.append(event_id) or 1,
    )

    worker = persist_worker.PersistWorker(batch_size=10)
    processed = worker.process_once()

    assert processed == 1
    assert acked == [b"1778935000000-0"]


def test_process_once_no_ack_when_persistence_unavailable(monkeypatch) -> None:
    acked = []

    monkeypatch.setattr(persist_worker.PersistWorker, "_claim_and_process_pending", lambda self: 0)
    monkeypatch.setattr(persist_worker, "is_already_processed", lambda key: False)
    monkeypatch.setattr(persist_worker, "mark_processed", lambda *args, **kwargs: None)
    monkeypatch.setattr(persist_worker, "clear_retry", lambda *args, **kwargs: None)
    monkeypatch.setattr(persist_worker, "increment_retry", lambda *args, **kwargs: 1)
    monkeypatch.setattr(persist_worker, "send_to_dead_letter", lambda **kwargs: "dlq-1")
    monkeypatch.setattr(
        persist_worker,
        "read_qa_turn_events",
        lambda **kwargs: [
            (
                "rag:events",
                [
                    (
                        b"1778935000001-0",
                        {
                            b"event_type": b"qa_turn",
                            b"session_id": b"sess-2",
                            b"question": b"Q",
                            b"answer": b"A",
                            b"conversation_title": b"t",
                            b"user_message_id": b"u2",
                            b"assistant_message_id": b"a2",
                            b"user_metadata": b"{}",
                            b"assistant_metadata": b"{}",
                            b"snapshot": b"[]",
                        },
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(persist_worker, "record_chat_turn", lambda **kwargs: False)
    monkeypatch.setattr(
        persist_worker,
        "ack_qa_turn_event",
        lambda event_id, **kwargs: acked.append(event_id) or 1,
    )

    worker = persist_worker.PersistWorker(batch_size=10)
    processed = worker.process_once()

    assert processed == 0
    assert acked == []
