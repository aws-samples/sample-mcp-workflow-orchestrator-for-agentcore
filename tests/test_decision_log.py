from orchestrator.decision_log import DecisionLog


def test_decision_log_records_and_renders():
    log = DecisionLog()
    log.record(action="select_server", server="pricing-mcp", tool="get_current_pricing",
               rationale="cost domain matched")
    md = log.to_markdown()
    assert "pricing-mcp" in md
    assert "Why" in md
