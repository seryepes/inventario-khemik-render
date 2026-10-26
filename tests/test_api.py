import tempfile
import unittest
from pathlib import Path

from backend import create_app

CSRF = {"X-Khemik-Request": "1"}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "DATABASE_URL": f"sqlite:///{Path(self.temp_dir.name) / 'api.db'}",
            "SECRET_KEY": "test-secret",
            "PRODUCTION": False,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def post(self, url, json=None, client=None):
        return (client or self.client).post(url, json=json, headers=CSRF)

    def setup_admin(self):
        return self.post("/api/auth/setup", {"username": "admin", "password": "admin-password"})

    def crear_y_entrar(self, username, role):
        self.post("/api/auth/users", {"username": username, "password": "clave-segura", "role": role})
        client = self.app.test_client()
        self.assertEqual(self.post("/api/auth/login", {"username": username, "password": "clave-segura"}, client).status_code, 200)
        return client

    def movimiento(self, **changes):
        data = {"fecha": "2026-01-01", "mvto": "Ingreso", "posicion": "1A", "producto": "Aluminio", "presentacion": "125 kg", "lote": "L-1", "cantidad": 1}
        data.update(changes)
        return data

    def test_primer_admin_y_proteccion_del_inventario(self):
        self.assertTrue(self.client.get("/api/auth/status").json["setupRequired"])
        self.assertEqual(self.client.get("/api/movimientos").status_code, 401)
        response = self.setup_admin()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["user"]["role"], "admin")
        self.assertEqual(self.client.get("/api/movimientos").status_code, 200)
        self.assertEqual(self.post("/api/auth/setup", {"username": "otro", "password": "other-password"}).status_code, 409)

    def test_peticiones_sin_encabezado_csrf_son_rechazadas(self):
        response = self.client.post("/api/auth/setup", json={"username": "admin", "password": "admin-password"})
        self.assertEqual(response.status_code, 403)

    def test_roles(self):
        self.setup_admin()
        operador = self.crear_y_entrar("operador", "operador")
        consulta = self.crear_y_entrar("consulta", "consulta")

        self.assertEqual(self.post("/api/movimientos", self.movimiento(), operador).status_code, 201)
        self.assertEqual(operador.delete("/api/movimientos", headers=CSRF).status_code, 403)
        self.assertEqual(operador.get("/api/auth/users").status_code, 403)
        self.assertEqual(consulta.get("/api/movimientos").status_code, 200)
        self.assertEqual(self.post("/api/movimientos", self.movimiento(), consulta).status_code, 403)
        self.assertEqual(self.client.delete("/api/movimientos", headers=CSRF).status_code, 200)

    def test_desactivar_usuario_cierra_su_sesion(self):
        self.setup_admin()
        operador = self.crear_y_entrar("operador", "operador")
        response = self.client.patch("/api/auth/users/operador", json={"activo": False}, headers=CSRF)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(operador.get("/api/movimientos").status_code, 401)

    def test_no_se_puede_quitar_el_ultimo_admin(self):
        self.setup_admin()
        response = self.client.patch("/api/auth/users/admin", json={"role": "operador"}, headers=CSRF)
        self.assertEqual(response.status_code, 400)

    def test_bloqueo_por_intentos_fallidos(self):
        self.setup_admin()
        client = self.app.test_client()
        codes = [self.post("/api/auth/login", {"username": "admin", "password": "incorrecta"}, client).status_code for _ in range(5)]
        self.assertEqual(codes, [401, 401, 401, 401, 429])
        response = self.post("/api/auth/login", {"username": "admin", "password": "admin-password"}, client)
        self.assertEqual(response.status_code, 429)

    def test_validaciones_de_credenciales(self):
        self.assertEqual(self.post("/api/auth/setup", {"username": "admin", "password": "short"}).status_code, 400)
        self.assertEqual(self.post("/api/auth/login", {"username": "nadie", "password": "wrong-password"}).status_code, 401)

    def test_errores_de_negocio_responden_json(self):
        self.setup_admin()
        response = self.post("/api/movimientos", self.movimiento(mvto="Salida", cantidad=3))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Stock insuficiente", response.json["error"])
        self.assertEqual(self.client.get("/api/no-existe").status_code, 404)

    def test_solo_se_publica_la_carpeta_frontend(self):
        with self.client.get("/js/servicio.js") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "text/javascript")
        with self.client.get("/") as response:
            self.assertIn("Content-Security-Policy", response.headers)
        for ruta in ("/app.py", "/backend/service.py", "/instance/khemik.db", "/../app.py", "/requirements.txt"):
            with self.client.get(ruta) as response:
                self.assertEqual(response.status_code, 404, ruta)


if __name__ == "__main__":
    unittest.main()
