"""End-to-end journeys through the API (deterministic planner, mocks in-process)."""

from conftest import answer, login, turn


async def test_journey1_emi_change_prepay_and_request(api):
    auth = await login(api, "C1001")
    assert auth["session"]["products"][0]["id"] == "PL-20391"

    events = await turn(api, auth, "My EMI increased this month. Why?")
    names = [e for e, _ in events]
    assert names[0] == "turn.started" and names[-1] == "turn.completed"
    assert "tool.started" in names and "card" in names
    text = answer(events)
    assert "₹17,195" in text and "₹17,416" in text and "11.25%" in text
    card = next(d for e, d in events if e == "card")
    assert card["type"] == "emi_change" and any(s["kind"] == "policy" for s in card["sources"])

    events = await turn(api, auth, "If I make a ₹50,000 prepayment today, how much interest would I save?")
    text = answer(events)
    assert "₹22,883" in text and "4 months" in text

    events = await turn(api, auth, "Go ahead and request a prepayment of ₹50,000 to reduce my tenure")
    proposal = next(d for e, d in events if e == "action.proposed")
    assert proposal["tier"] == "confirm_otp" and proposal["demo_otp"]
    bad = (await api.post(f"/v1/actions/{proposal['action_id']}/confirm", json={"otp": "000000"},
                          headers=auth["headers"])).json()
    assert bad["status"] == "otp_invalid"
    ok = (await api.post(f"/v1/actions/{proposal['action_id']}/confirm", json={"otp": proposal["demo_otp"]},
                         headers=auth["headers"])).json()
    assert ok["status"] == "succeeded" and ok["request_id"].startswith("SR-")
    reqs = (await api.get("/v1/requests", headers=auth["headers"])).json()
    assert any(r["request_id"] == ok["request_id"] for r in reqs)


async def test_journey2_failed_payments_and_dispute(api):
    auth = await login(api, "C1002")
    events = await turn(api, auth, "Show me the payments that failed in the last six months and explain what happened")
    text = answer(events)
    assert "2 debits failed" in text and "last payment attempt" in text and "mandate had expired" in text and "₹590" in text
    events = await turn(api, auth, "Raise a dispute for the duplicate charge")
    proposal = next(d for e, d in events if e == "action.proposed")
    assert proposal["tier"] == "confirm"
    assert any(row["value"] == "₹590" for row in proposal["summary"])
    ok = (await api.post(f"/v1/actions/{proposal['action_id']}/confirm", json={"via": "voice"},
                         headers=auth["headers"])).json()
    assert ok["status"] == "succeeded"


async def test_journey3_voice_follow_ups_keep_context(api):
    auth = await login(api, "C1001")
    events = await turn(api, auth, "What's my next EMI?", channel="voice")
    assert "₹17,416" in answer(events) and "5 Nov 2026" in answer(events)
    events = await turn(api, auth, "Actually, check my last payment first", channel="voice")
    assert "5 Oct 2026" in answer(events) or "payment" in answer(events).lower()
    events = await turn(api, auth, "Okay, now would paying ₹20,000 extra reduce my tenure?", channel="voice")
    text = answer(events)
    assert "₹20,000" in text and "₹9,483" in text and "1 month" in text


async def test_journey4_foreclosure_lock_in_and_statement(api):
    auth = await login(api, "C1003")
    events = await turn(api, auth, "Am I eligible for foreclosure without a penalty?")
    text = answer(events)
    assert text.startswith("No") and "20 Feb 2027" in text
    events = await turn(api, auth, "Send me a statement")
    proposal = next(d for e, d in events if e == "action.proposed")
    assert proposal["tier"] == "confirm"  # it files a request, so the customer says yes first
    ok = (await api.post(f"/v1/actions/{proposal['action_id']}/confirm", json={"via": "text"},
                         headers=auth["headers"])).json()
    assert ok["status"] == "succeeded"
    reqs = (await api.get("/v1/requests", headers=auth["headers"])).json()
    statement = next(r for r in reqs if r["type"] == "statement")
    pdf = await api.get(f"/v1/statements/{statement['request_id']}", headers=auth["headers"])
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"


async def test_overview_and_metrics(api):
    auth = await login(api, "C1002")
    ov = (await api.get("/v1/account/overview", headers=auth["headers"])).json()
    assert ov["loans"][0]["loan_id"] == "PL-18822"
    assert any(p["status"] == "failed" for p in ov["payments"])
    await turn(api, auth, "What's my next EMI?")
    m = (await api.get("/v1/metrics/latency", headers=auth["headers"])).json()
    assert any(s["name"] == "Turn complete" for s in m["stages"])
    assert any(s["system"] == "Loan Management" for s in m["systems"])


async def test_unknown_question_gets_help(api):
    auth = await login(api, "C1001")
    events = await turn(api, auth, "What's the weather like?")
    assert "I can explain" in answer(events)


async def test_journey5_card_pack_statement_and_dispute(api):
    auth = await login(api, "C1004")
    types = {p["type"] for p in auth["session"]["products"]}
    assert types == {"loan", "card"}
    events = await turn(api, auth, "Why is my card statement higher this month?")
    text = answer(events)
    assert "₹25,991" in text and "₹18,449" in text and "EMI 1 of 6" in text
    events = await turn(api, auth, "Dispute the ₹4,299 charge from 12 October, I don't recognise it")
    proposal = next(d for e, d in events if e == "action.proposed")
    assert proposal["action"] == "cards_dispute_card_transaction"
    assert any("QuickMart" in row["value"] for row in proposal["summary"])
    ok = (await api.post(f"/v1/actions/{proposal['action_id']}/confirm", json={}, headers=auth["headers"])).json()
    assert ok["status"] == "succeeded"
    # the same customer's loan questions still work alongside the card pack
    events = await turn(api, auth, "Why did my EMI go up?")
    assert "11.75%" in answer(events)
    ov = (await api.get("/v1/account/overview", headers=auth["headers"])).json()
    assert ov["cards"][0]["last4"] == "4417" and ov["loans"][0]["loan_id"] == "PL-22010"


async def test_two_part_question_is_answered_in_full_without_a_model(api):
    """The brief's headline question: both parts answered by the deterministic planner, tools in parallel."""
    auth = await login(api, "C1001")
    events = await turn(api, auth, "My EMI increased this month. Why? And if I make a ₹50,000 prepayment today, "
                                   "how much interest would I save?")
    tools = [d["tool"] for e, d in events if e == "tool.started"]
    assert set(tools) == {"loans_explain_emi_change", "loans_prepayment_options"}
    reply = answer(events)
    assert "₹50,000" in reply and ("increase" in reply.lower() or "rate" in reply.lower())


async def test_one_question_still_calls_one_tool(api):
    auth = await login(api, "C1001")
    events = await turn(api, auth, "What's my next EMI?")
    assert len([1 for e, _ in events if e == "tool.started"]) == 1



async def test_a_negated_request_is_not_filed(api):
    auth = await login(api, "C1003")
    statements = lambda reqs: [r for r in reqs if r["type"] == "statement"]  # noqa: E731
    before = statements((await api.get("/v1/requests", headers=auth["headers"])).json())
    for text in ("I don't want a statement", "No need to send a statement, what is my EMI?"):
        events = await turn(api, auth, text)
        assert not [d for e, d in events if e == "action.proposed"], text
        assert "loans_generate_statement" not in [d["tool"] for e, d in events if e == "tool.started"], text
    after = statements((await api.get("/v1/requests", headers=auth["headers"])).json())
    assert len(after) == len(before)
