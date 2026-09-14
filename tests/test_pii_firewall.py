"""Firewall masking + re-hydration across every provider payload shape."""

import json

from smart_llm.pii.firewall import PiiFirewall, TokenVault

SSN = "123-45-6789"
EMAIL = "jane@example.com"


def _fw() -> PiiFirewall:
    return PiiFirewall()


def test_mask_text_round_trip():
    fw, vault = _fw(), TokenVault()
    masked = fw.mask_text(f"my ssn is {SSN} ok", vault)
    assert SSN not in masked
    assert vault.restore_text(masked) == f"my ssn is {SSN} ok"


def test_token_is_stable_for_same_value():
    fw, vault = _fw(), TokenVault()
    a = fw.mask_text(f"{SSN} and again {SSN}", vault)
    # Same value tokenised once → single token appears twice.
    assert a.count("⟦SSN_1⟧") == 2
    assert vault.token_count() == 1


def test_mask_obj_nested_round_trip():
    fw, vault = _fw(), TokenVault()
    obj = {"a": SSN, "b": ["x", {"c": EMAIL}], "n": 5}
    masked = fw.mask_obj(obj, vault)
    assert SSN not in json.dumps(masked)
    assert EMAIL not in json.dumps(masked)
    assert fw.restore_obj(masked, vault) == obj


def test_mask_payload_plain_string():
    fw, vault = _fw(), TokenVault()
    sys_m, inp_m = fw.mask_payload(f"agent for {EMAIL}", f"contact {SSN}", vault)
    assert EMAIL not in sys_m
    assert SSN not in inp_m


def test_mask_payload_anthropic_blocks():
    fw, vault = _fw(), TokenVault()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"ssn {SSN}"},
                {"type": "tool_use", "id": "t", "name": "q", "input": {"email": EMAIL}},
                {"type": "tool_result", "tool_use_id": "t", "content": f"row {SSN}"},
                {"type": "image", "source": {"type": "base64", "data": "QUJD"}},
            ],
        }
    ]
    _, masked = fw.mask_payload("sys", messages, vault)
    blob = json.dumps(masked)
    assert SSN not in blob and EMAIL not in blob
    # Image bytes are untouched.
    assert masked[0]["content"][3]["source"]["data"] == "QUJD"
    assert fw.restore_obj(masked, vault) == messages


def test_mask_payload_openai_tool_calls_arguments_stay_valid_json():
    fw, vault = _fw(), TokenVault()
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": json.dumps({"ssn": SSN, "note": "ok"}),
                    },
                }
            ],
        }
    ]
    _, masked = fw.mask_payload("sys", messages, vault)
    args = masked[0]["tool_calls"][0]["function"]["arguments"]
    assert SSN not in args
    parsed = json.loads(args)  # still valid JSON
    assert vault.restore_text(parsed["ssn"]) == SSN


def test_mask_payload_gemini_parts():
    fw, vault = _fw(), TokenVault()
    messages = [
        {
            "role": "user",
            "parts": [
                {"text": f"email {EMAIL}"},
                {"function_call": {"name": "q", "args": {"ssn": SSN}}},
                {"function_response": {"name": "q", "response": {"found": SSN}}},
            ],
        }
    ]
    _, masked = fw.mask_payload("sys", messages, vault)
    blob = json.dumps(masked)
    assert SSN not in blob and EMAIL not in blob
    assert fw.restore_obj(masked, vault) == messages


def test_no_pii_leaves_payload_unchanged():
    fw, vault = _fw(), TokenVault()
    _, masked = fw.mask_payload("plain system", "just a normal question", vault)
    assert masked == "just a normal question"
    assert vault.is_empty
