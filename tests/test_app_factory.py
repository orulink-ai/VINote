import unittest

from fastapi.testclient import TestClient

from app import create_app


class AppFactoryTest(unittest.TestCase):
    def test_create_app_registers_routes_and_healthcheck(self):
        app = create_app()
        client = TestClient(app)

        try:
            response = client.get("/healthz")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_regular_users_cannot_trigger_server_dependency_installation(self):
        app = create_app()

        route_paths = {route.path for route in app.routes}

        self.assertNotIn("/api/stt-profiles/local-support/install", route_paths)


if __name__ == "__main__":
    unittest.main()
