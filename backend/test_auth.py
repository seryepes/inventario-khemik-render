import tempfile
import unittest
from pathlib import Path

from . import app as app_module
from .service import InventarioService


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_service = app_module.service
        app_module.service = InventarioService(Path(self.temp_dir.name) / "auth-test.db")
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.service = self.original_service
        self.temp_dir.cleanup()

    def test_first_admin_setup_and_inventory_protection(self):
        response = self.client.get("/api/auth/status")
        self.assertTrue(response.json["setupRequired"])
        self.assertEqual(self.client.get("/api/movimientos").status_code, 401)

        response = self.client.post(
            "/api/auth/setup",
            json={"username": "admin", "password": "admin-password"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["user"]["role"], "admin")
        self.assertEqual(self.client.get("/api/movimientos").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/auth/setup",
                json={"username": "other", "password": "other-password"},
            ).status_code,
            409,
        )

    def test_admin_creates_user_and_user_cannot_manage_accounts(self):
        self.client.post(
            "/api/auth/setup",
            json={"username": "admin", "password": "admin-password"},
        )
        response = self.client.post(
            "/api/auth/users",
            json={"username": "operador", "password": "user-password"},
        )
        self.assertEqual(response.status_code, 201)

        self.client.post("/api/auth/logout")
        response = self.client.post(
            "/api/auth/login",
            json={"username": "operador", "password": "user-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/movimientos").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/users").status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/auth/users",
                json={"username": "otro", "password": "other-password"},
            ).status_code,
            403,
        )

    def test_invalid_password_and_login_are_rejected(self):
        response = self.client.post(
            "/api/auth/setup",
            json={"username": "admin", "password": "short"},
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/auth/login",
            json={"username": "unknown", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
