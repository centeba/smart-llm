def test_key_manager_registration(key_manager):
    """Test that providers and keys are correctly registered."""
    key_manager.register_provider("openai", ["key1", "key2"])
    assert "openai" in key_manager.keys
    assert key_manager.keys["openai"] == ["key1", "key2"]
    assert key_manager.indices["openai"] == 0
    assert key_manager.usage_counts["openai"] == 0


def test_key_manager_rotation(key_manager):
    """Test automatic key rotation after reaching the usage interval."""
    # interval is 2 (from conftest fixture)
    key_manager.register_provider("test_provider", ["k1", "k2", "k3"])

    # 1st call
    assert key_manager.get_key("test_provider") == "k1"
    assert key_manager.usage_counts["test_provider"] == 1

    # 2nd call -> should still be k1, usage count becomes 2
    assert key_manager.get_key("test_provider") == "k1"
    assert key_manager.usage_counts["test_provider"] == 2

    # 3rd call -> interval (2) reached, should rotate to k2
    assert key_manager.get_key("test_provider") == "k2"
    assert key_manager.usage_counts["test_provider"] == 1
    assert key_manager.indices["test_provider"] == 1


def test_key_manager_rotate_on_failure(key_manager):
    """Test immediate rotation on manual failure signal."""
    key_manager.register_provider("test", ["keyA", "keyB"])

    assert key_manager.get_key("test") == "keyA"
    key_manager.rotate_on_failure("test")

    # Should now return keyB even though usage interval wasn't reached
    assert key_manager.indices["test"] == 1
    assert key_manager.get_key("test") == "keyB"
    assert key_manager.usage_counts["test"] == 1


def test_key_manager_case_insensitivity(key_manager):
    """Ensure provider names are treated as case-insensitive."""
    key_manager.register_provider("OpenAI", ["keyX"])
    assert key_manager.get_key("openai") == "keyX"
    assert key_manager.get_key("OPENAI") == "keyX"
