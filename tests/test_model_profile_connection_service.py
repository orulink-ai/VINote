import unittest
from unittest.mock import Mock, patch

from app.models.model_profile import ModelProfileTestRequest
from app.services.model_profile_connection_service import ModelProfileConnectionService


class ModelProfileConnectionServiceTest(unittest.TestCase):
    def test_openai_connection_test_uses_generation_temperature(self):
        response = Mock()
        response.raise_for_status.return_value = None

        with patch("app.services.model_profile_connection_service.httpx.post", return_value=response) as post:
            result = ModelProfileConnectionService().test_connection(
                ModelProfileTestRequest(
                    provider="openai-compatible",
                    base_url="https://api.moonshot.cn/v1",
                    model_name="kimi-k2.5",
                    api_key="test-key",
                )
            )

        self.assertTrue(result.ok)
        request_body = post.call_args.kwargs["json"]
        self.assertEqual(request_body["temperature"], 0.7)
        self.assertEqual(
            request_body["messages"],
            [
                {"role": "system", "content": "You are a concise connection test assistant."},
                {"role": "user", "content": "ping"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
