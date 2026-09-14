import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from smart_llm.base import LLMResponse


@pytest.fixture
def client():
    """Create a test client with mocked agent manager."""
    # We need to patch before importing the app module
    with patch.dict(os.environ, {}, clear=False):
        # Re-import to get fresh app state
        import importlib

        import smart_llm.api.main as main_module

        importlib.reload(main_module)

        # Mark that we have an agent
        main_module._has_agent = True

        # Mock the manager.analyze method
        mock_response = LLMResponse(
            data={"result": "test"},
            provider="openai",
            metadata={"agent_name": "test"},
        )
        main_module.manager.analyze = AsyncMock(return_value=mock_response)

        yield TestClient(main_module.app)


class TestInputSizeLimits:
    def test_accepts_normal_input(self, client):
        response = client.post(
            "/analyze",
            json={"input_text": "Hello, analyze this."},
        )
        assert response.status_code == 200

    def test_rejects_oversized_input(self, client):
        # Default limit is 50,000 chars
        long_text = "x" * 50_001
        response = client.post(
            "/analyze",
            json={"input_text": long_text},
        )
        assert response.status_code == 422

    def test_rejects_empty_input(self, client):
        response = client.post(
            "/analyze",
            json={"input_text": "   "},
        )
        assert response.status_code == 422

    def test_custom_max_length(self):
        """Test that SMART_LLM_MAX_INPUT_LENGTH env var is respected."""
        with patch.dict(os.environ, {"SMART_LLM_MAX_INPUT_LENGTH": "100"}):
            import importlib

            import smart_llm.api.main as main_module

            importlib.reload(main_module)
            main_module._has_agent = True
            mock_response = LLMResponse(
                data={"result": "ok"}, provider="openai", metadata={}
            )
            main_module.manager.analyze = AsyncMock(return_value=mock_response)
            client = TestClient(main_module.app)

            # Should reject 101-char input with 100-char limit
            response = client.post(
                "/analyze",
                json={"input_text": "x" * 101},
            )
            assert response.status_code == 422


class TestSafeErrorHandling:
    def test_no_agents_returns_503(self):
        import importlib

        import smart_llm.api.main as main_module

        importlib.reload(main_module)
        main_module._has_agent = False
        client = TestClient(main_module.app)

        response = client.post(
            "/analyze",
            json={"input_text": "Hello"},
        )
        assert response.status_code == 503
        assert (
            "no AI agents" in response.json()["detail"].lower()
            or "unavailable" in response.json()["detail"].lower()
        )

    def test_internal_error_does_not_leak_details(self, client):
        import smart_llm.api.main as main_module

        main_module.manager.analyze = AsyncMock(
            side_effect=RuntimeError("secret internal API key: sk-12345")
        )

        response = client.post(
            "/analyze",
            json={"input_text": "Hello"},
        )
        assert response.status_code == 500
        body = response.json()
        assert "sk-12345" not in body["detail"]
        assert body["detail"] == "Internal server error"

    def test_prompt_injection_returns_400(self, client):
        import smart_llm.api.main as main_module
        from smart_llm.security import PromptInjectionError

        main_module.manager.analyze = AsyncMock(
            side_effect=PromptInjectionError("injection detected")
        )

        response = client.post(
            "/analyze",
            json={"input_text": "Hello"},
        )
        assert response.status_code == 400
        assert "harmful" in response.json()["detail"].lower()

    def test_schema_validation_returns_502(self, client):
        import smart_llm.api.main as main_module
        from smart_llm.security import SchemaValidationError

        main_module.manager.analyze = AsyncMock(
            side_effect=SchemaValidationError("bad schema", validation_errors=[])
        )

        response = client.post(
            "/analyze",
            json={"input_text": "Hello"},
        )
        assert response.status_code == 502


class TestAPIKeyAuth:
    def test_no_keys_configured_allows_anonymous(self, client):
        """When SMART_LLM_API_KEYS is not set, auth is disabled."""
        response = client.post(
            "/analyze",
            json={"input_text": "Hello"},
        )
        assert response.status_code == 200

    def test_valid_key_accepted(self):
        with patch.dict(os.environ, {"SMART_LLM_API_KEYS": "key1,key2"}):
            import importlib

            import smart_llm.api.main as main_module

            importlib.reload(main_module)
            main_module._has_agent = True
            mock_response = LLMResponse(
                data={"result": "ok"}, provider="openai", metadata={}
            )
            main_module.manager.analyze = AsyncMock(return_value=mock_response)
            client = TestClient(main_module.app)

            response = client.post(
                "/analyze",
                json={"input_text": "Hello"},
                headers={"X-API-Key": "key1"},
            )
            assert response.status_code == 200

    def test_invalid_key_rejected(self):
        with patch.dict(os.environ, {"SMART_LLM_API_KEYS": "key1,key2"}):
            import importlib

            import smart_llm.api.main as main_module

            importlib.reload(main_module)
            main_module._has_agent = True
            client = TestClient(main_module.app)

            response = client.post(
                "/analyze",
                json={"input_text": "Hello"},
                headers={"X-API-Key": "wrong_key"},
            )
            assert response.status_code == 401

    def test_missing_key_rejected(self):
        with patch.dict(os.environ, {"SMART_LLM_API_KEYS": "key1"}):
            import importlib

            import smart_llm.api.main as main_module

            importlib.reload(main_module)
            main_module._has_agent = True
            client = TestClient(main_module.app)

            response = client.post(
                "/analyze",
                json={"input_text": "Hello"},
            )
            assert response.status_code == 401

    def test_health_endpoint_no_auth_required(self):
        with patch.dict(os.environ, {"SMART_LLM_API_KEYS": "key1"}):
            import importlib

            import smart_llm.api.main as main_module

            importlib.reload(main_module)
            client = TestClient(main_module.app)

            response = client.get("/health")
            assert response.status_code == 200


class TestRateLimiting:
    def test_allows_requests_under_limit(self):
        import importlib

        import smart_llm.api.main as main_module

        importlib.reload(main_module)
        main_module._has_agent = True
        mock_response = LLMResponse(
            data={"result": "ok"}, provider="openai", metadata={}
        )
        main_module.manager.analyze = AsyncMock(return_value=mock_response)

        # Re-add middleware with low limit for testing
        from smart_llm.api.middleware import RateLimitMiddleware

        # Clear existing middleware and add with low limit
        main_module.app = main_module.FastAPI(
            title="Test", lifespan=main_module.lifespan
        )
        main_module.app.add_middleware(
            RateLimitMiddleware, max_requests=5, window_seconds=60
        )

        @main_module.app.post("/analyze")
        async def analyze(request: main_module.AnalyzeRequest):
            resp = await main_module.manager.analyze(request.input_text)
            return {"data": resp.data, "metadata": resp.metadata}

        client = TestClient(main_module.app)

        # Should succeed for first 5 requests
        for i in range(5):
            response = client.post("/analyze", json={"input_text": f"test {i}"})
            assert response.status_code == 200, f"Request {i} failed"

        # 6th request should be rate limited
        response = client.post("/analyze", json={"input_text": "too many"})
        assert response.status_code == 429
        assert "rate limit" in response.json()["detail"].lower()
