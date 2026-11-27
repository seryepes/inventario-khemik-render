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
        self.app.extensions["khemik"]["inventario"]._session_factory.kw["bind"].dispose()
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

    def test_coordinador_tiene_acceso_amplio_pero_no_puede_borrar_todo(self):
        self.setup_admin()
        coordinador = self.crear_y_entrar("coordinador", "coordinador")

        self.assertEqual(coordinador.get("/api/auth/users").status_code, 200)
        self.assertEqual(
            self.post("/api/catalogos/productos", {"nombre": "Cobre", "categoria": "materia_prima"}, coordinador).status_code,
            201,
        )
        self.assertEqual(self.post("/api/importar", [self.movimiento()], coordinador).status_code, 200)
        self.assertEqual(self.post("/api/restaurar", [self.movimiento()], coordinador).status_code, 200)
        self.assertEqual(coordinador.get("/api/auditoria").status_code, 200)
        self.assertEqual(coordinador.delete("/api/movimientos", headers=CSRF).status_code, 403)

    def test_solo_admin_asigna_roles_privilegiados_y_coordinador_no_altera_cuentas_privilegiadas(self):
        self.setup_admin()
        coordinador = self.crear_y_entrar("coordinador", "coordinador")
        self.assertEqual(
            self.post(
                "/api/auth/users",
                {"username": "nuevo", "password": "clave-segura", "role": "operador"},
                coordinador,
            ).status_code,
            201,
        )
        for role in ("admin", "coordinador"):
            with self.subTest(role=role):
                response = self.post(
                    "/api/auth/users",
                    {"username": f"nuevo-{role}", "password": "clave-segura", "role": role},
                    coordinador,
                )
                self.assertEqual(response.status_code, 403)

        self.assertEqual(
            coordinador.patch(
                "/api/auth/users/nuevo", json={"role": "coordinador"}, headers=CSRF,
            ).status_code,
            403,
        )
        self.assertEqual(
            coordinador.patch(
                "/api/auth/users/admin", json={"activo": False}, headers=CSRF,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                "/api/auth/users/nuevo", json={"role": "coordinador"}, headers=CSRF,
            ).status_code,
            200,
        )

    def test_admin_crea_rol_personalizado_y_asigna_permisos_sin_borrar_todo(self):
        self.setup_admin()
        creado = self.post("/api/auth/roles", {
            "nombre": "Auditoría de lectura",
            "permisos": ["ver_inventario", "ver_auditoria"],
        })
        self.assertEqual(creado.status_code, 201)
        codigo = creado.json["codigo"]

        self.assertEqual(
            self.post("/api/auth/roles", {
                "nombre": "Rol con borrado",
                "permisos": ["ver_inventario", "borrar_todo"],
            }).status_code,
            400,
        )
        self.assertEqual(
            self.post("/api/auth/users", {
                "username": "auditor",
                "password": "clave-segura",
                "role": codigo,
            }).status_code,
            201,
        )
        auditor = self.app.test_client()
        self.assertEqual(
            self.post("/api/auth/login", {"username": "auditor", "password": "clave-segura"}, auditor).status_code,
            200,
        )
        self.assertEqual(auditor.get("/api/auth/status").json["user"]["roleName"], "Auditoría de lectura")
        self.assertEqual(auditor.get("/api/movimientos").status_code, 200)
        self.assertEqual(auditor.get("/api/auditoria").status_code, 200)
        self.assertEqual(self.post("/api/movimientos", self.movimiento(), auditor).status_code, 403)
        self.assertEqual(auditor.delete("/api/movimientos", headers=CSRF).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/auth/roles/{codigo}", headers=CSRF).status_code, 409)

        self.assertEqual(
            self.client.patch(
                "/api/auth/users/auditor", json={"role": "consulta"}, headers=CSRF,
            ).status_code,
            200,
        )
        self.assertEqual(self.client.delete(f"/api/auth/roles/{codigo}", headers=CSRF).status_code, 200)

    def test_solo_admin_puede_configurar_roles_y_se_validan_dependencias(self):
        self.setup_admin()
        coordinador = self.crear_y_entrar("coordinador", "coordinador")
        self.assertEqual(
            self.post(
                "/api/auth/roles",
                {"nombre": "No autorizado", "permisos": ["ver_inventario"]},
                coordinador,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.post("/api/auth/roles", {
                "nombre": "Movimiento sin consulta",
                "permisos": ["gestionar_movimientos"],
            }).status_code,
            400,
        )

    def test_rol_personalizado_solo_accede_a_los_modulos_seleccionados(self):
        self.setup_admin()
        role = self.post("/api/auth/roles", {
            "nombre": "Gestor de catálogos",
            "permisos": ["gestionar_catalogos"],
        }).json
        self.assertEqual(
            self.post("/api/auth/users", {
                "username": "catalogos",
                "password": "clave-segura",
                "role": role["codigo"],
            }).status_code,
            201,
        )
        catalogos = self.app.test_client()
        self.assertEqual(
            self.post("/api/auth/login", {"username": "catalogos", "password": "clave-segura"}, catalogos).status_code,
            200,
        )
        self.assertEqual(catalogos.get("/api/catalogos").status_code, 200)
        self.assertEqual(catalogos.get("/api/movimientos").status_code, 403)
        self.assertEqual(
            self.post(
                "/api/catalogos/productos",
                {"nombre": "Cobre", "categoria": "materia_prima"},
                catalogos,
            ).status_code,
            201,
        )
        self.assertEqual(catalogos.delete("/api/movimientos", headers=CSRF).status_code, 403)

    def test_admin_y_operador_pueden_marcar_posicion_peligrosa(self):
        self.setup_admin()
        ruta = "/api/posiciones/PISO%20PLANTA1/peligro"
        response = self.client.patch(
            ruta, json={"peligrosa": True, "titulo": "Químicos corrosivos"}, headers=CSRF,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["tituloPeligro"], "Químicos corrosivos")

        operador = self.crear_y_entrar("operador", "operador")
        response = operador.patch(
            ruta, json={"peligrosa": True, "titulo": "Riesgo eléctrico"}, headers=CSRF,
        )
        self.assertEqual(response.status_code, 200)
        mapa = operador.get("/api/posiciones").json
        self.assertTrue(mapa["PISO PLANTA1"]["peligrosa"])

        consulta = self.crear_y_entrar("consulta", "consulta")
        response = consulta.patch(
            ruta, json={"peligrosa": False, "titulo": ""}, headers=CSRF,
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_y_operador_pueden_modificar_estado_de_lote(self):
        self.setup_admin()
        self.assertEqual(self.post("/api/movimientos", self.movimiento()).status_code, 201)
        ruta = "/api/lotes/estado"
        response = self.client.patch(
            ruta, json={"producto": "Aluminio", "lote": "L-1", "estado": "aprobado"}, headers=CSRF,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["estado"], "aprobado")
        self.assertTrue(response.json["manual"])

        operador = self.crear_y_entrar("operador", "operador")
        response = operador.patch(
            ruta, json={"producto": "Aluminio", "lote": "L-1", "estado": "cuarentena"}, headers=CSRF,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(operador.get("/api/lotes/estados").json[0]["estado"], "cuarentena")

        consulta = self.crear_y_entrar("consulta", "consulta")
        response = consulta.patch(
            ruta, json={"producto": "Aluminio", "lote": "L-1", "estado": "aprobado"}, headers=CSRF,
        )
        self.assertEqual(response.status_code, 403)

    def test_posicion_peligrosa_exige_titulo(self):
        self.setup_admin()
        response = self.client.patch(
            "/api/posiciones/1A/peligro",
            json={"peligrosa": True, "titulo": ""},
            headers=CSRF,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("título", response.json["error"])

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

    def test_descarga_auditoria_es_csv_sin_mostrar_registros_en_json(self):
        self.setup_admin()
        response = self.client.get("/api/auditoria/exportar")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        texto = response.data.decode("utf-8-sig")
        self.assertIn("Fecha,Usuario,Acción,Detalle", texto)

    def test_crear_producto_exige_categoria_y_la_publica_en_catalogo(self):
        self.setup_admin()
        sin_categoria = self.post("/api/catalogos/productos", {"nombre": "Cobre"})
        self.assertEqual(sin_categoria.status_code, 400)

        creado = self.post("/api/catalogos/productos", {
            "nombre": "Cobre",
            "categoria": "materia_prima",
        })
        self.assertEqual(creado.status_code, 201)
        self.assertEqual(creado.json["categoria"], "materia_prima")
        catalogo = self.client.get("/api/catalogos").json
        cobre = next(p for p in catalogo["productos"] if p["nombre"] == "Cobre")
        self.assertEqual(cobre["categoria"], "materia_prima")

    def test_admin_puede_editar_borrar_y_reactivar_producto_sin_perder_historial(self):
        self.setup_admin()
        movimiento = self.post("/api/movimientos", self.movimiento())
        self.assertEqual(movimiento.status_code, 201)
        aluminio = next(
            producto for producto in self.client.get("/api/catalogos").json["productos"]
            if producto["nombre"] == "Aluminio"
        )
        producto_id = aluminio["id"]

        editado = self.client.patch(
            f"/api/catalogos/productos/{producto_id}",
            json={"nombre": "Aluminio Industrial", "categoria": "materia_prima"},
            headers=CSRF,
        )
        self.assertEqual(editado.status_code, 200)
        self.assertEqual(editado.json["nombre"], "Aluminio Industrial")
        self.assertEqual(editado.json["categoria"], "materia_prima")
        self.assertEqual(self.client.get("/api/movimientos").json[0]["producto"], "Aluminio Industrial")

        borrado = self.client.delete(f"/api/catalogos/productos/{producto_id}", headers=CSRF)
        self.assertEqual(borrado.status_code, 200)
        self.assertFalse(borrado.json["activo"])
        self.assertEqual(self.client.get("/api/movimientos").json[0]["id"], movimiento.json["id"])
        self.assertEqual(
            self.post("/api/movimientos", self.movimiento(producto="Aluminio Industrial")).status_code,
            400,
        )

        reactivado = self.client.patch(
            f"/api/catalogos/productos/{producto_id}",
            json={"activo": True},
            headers=CSRF,
        )
        self.assertEqual(reactivado.status_code, 200)
        self.assertTrue(reactivado.json["activo"])

    def test_operador_no_puede_modificar_productos_del_catalogo(self):
        self.setup_admin()
        operador = self.crear_y_entrar("operador", "operador")
        aluminio = next(
            producto for producto in operador.get("/api/catalogos").json["productos"]
            if producto["nombre"] == "Aluminio"
        )
        ruta = f"/api/catalogos/productos/{aluminio['id']}"
        self.assertEqual(
            operador.patch(ruta, json={"nombre": "Nuevo nombre"}, headers=CSRF).status_code, 403,
        )
        self.assertEqual(operador.delete(ruta, headers=CSRF).status_code, 403)

        coordinador = self.crear_y_entrar("coordinador", "coordinador")
        self.assertEqual(
            coordinador.patch(ruta, json={"nombre": "Aluminio para coordinador"}, headers=CSRF).status_code,
            200,
        )

    def test_movimiento_guarda_y_conserva_fecha_hora_de_creacion(self):
        self.setup_admin()
        response = self.post("/api/movimientos", self.movimiento(posicion="PISO PLANTA1"))

        self.assertEqual(response.status_code, 201)
        creado_en = response.json["creadoEn"]
        response = self.client.put(
            f"/api/movimientos/{response.json['id']}",
            json={**self.movimiento(posicion="PISO PLANTA1", cantidad=2), "id": response.json["id"]},
            headers=CSRF,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["creadoEn"], creado_en)

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
