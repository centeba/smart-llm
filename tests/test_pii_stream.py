"""StreamRestorer — token-boundary-safe re-hydration of streamed deltas."""

from smart_llm.pii.firewall import StreamRestorer, TokenVault


def _vault_with(value: str, pii_type: str) -> tuple[TokenVault, str]:
    vault = TokenVault()
    token = vault.tokenize(value, pii_type)
    return vault, token


def _run(vault: TokenVault, full: str, chunks: list[str]) -> str:
    r = StreamRestorer(vault)
    out = "".join(r.push(c) for c in chunks)
    out += r.flush()
    return out


def test_token_split_across_single_char_chunks():
    vault, token = _vault_with("123-45-6789", "SSN")
    full = f"the ssn is {token} done"
    got = _run(vault, full, list(full))  # one char per chunk — worst case
    assert got == "the ssn is 123-45-6789 done"


def test_token_split_at_every_boundary():
    vault, token = _vault_with("a@b.com", "EMAIL")
    full = f"x{token}y"
    for i in range(len(full) + 1):
        got = _run(vault, full, [full[:i], full[i:]])
        assert got == "xa@b.comy", f"split at {i} failed"


def test_multiple_tokens_in_one_stream():
    vault = TokenVault()
    t1 = vault.tokenize("123-45-6789", "SSN")
    t2 = vault.tokenize("a@b.com", "EMAIL")
    full = f"{t1} and {t2}"
    got = _run(vault, full, list(full))
    assert got == "123-45-6789 and a@b.com"


def test_stray_open_bracket_flushed_verbatim():
    vault, _ = _vault_with("123-45-6789", "SSN")
    r = StreamRestorer(vault)
    out = r.push("value is ⟦ not a token")
    out += r.flush()
    assert out == "value is ⟦ not a token"


def test_plain_text_passes_through_immediately():
    vault = TokenVault()
    r = StreamRestorer(vault)
    assert r.push("hello ") == "hello "
    assert r.push("world") == "world"
    assert r.flush() == ""


def test_partial_token_never_emits_raw_bracket_early():
    vault, token = _vault_with("123-45-6789", "SSN")
    r = StreamRestorer(vault)
    # Feed the opening bracket + type but not the close — must hold back.
    emitted = r.push("ssn ⟦SSN_1")
    assert "⟦" not in emitted  # dangling opener held, not leaked
    emitted += r.push("⟧ ok")
    emitted += r.flush()
    assert emitted == "ssn 123-45-6789 ok"
