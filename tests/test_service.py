import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

from backend.database import inicializar_base
from backend.domain import Movimiento
from backend.service import InventarioService


class InventarioServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.session_factory = inicializar_base(f"sqlite:///{Path(self.temp_dir.name) / 'test.db'}")
        self.service = InventarioService(self.session_factory)

    def tearDown(self):
        self.session_factory.kw["bind"].dispose()
        self.temp_dir.cleanup()

    def movimiento(self, **changes):
        data = {"fecha": "2026-01-01", "mvto": "Ingreso", "posicion": "1A", "producto": "Aluminio", "presentacion": "125 kg", "lote": "L-1", "cantidad": 2}
        data.update(changes)
        return data

    def guardar(self, **changes):
        return self.service.guardar_movimiento(self.movimiento(**changes), None)

    def test_ingreso_y_stock(self):
        self.guardar()
        self.assertEqual(self.service.stock()[0]["cantidad"], 2)

    def test_capacidad_por_posicion(self):
        self.guardar(cantidad=5)
        with self.assertRaisesRegex(ValueError, "está llena"):
            self.guardar(lote="L-2", cantidad=1)

    def test_ubicacion_no_acepta_otro_producto_mientras_tiene_stock(self):
        posicion = "PISO PLANTA1"
        self.guardar(posicion=posicion)
        self.guardar(posicion=posicion, lote="L-2", cantidad=1)

        with self.assertRaisesRegex(ValueError, "está ocupada por Aluminio"):
            self.guardar(posicion=posicion, producto="Magnesio", lote="M-1")

    def test_traslado_no_permite_destino_ocupado_por_otro_producto(self):
        self.guardar(posicion="1A")
        self.guardar(posicion="PISO PLANTA2", producto="Magnesio", lote="M-1")

        with self.assertRaisesRegex(ValueError, "está ocupada por Magnesio"):
            self.service.guardar_traslado(
                self.movimiento(posicion="1A", posicionDestino="PISO PLANTA2"), None,
            )

    def test_posiciones_de_piso_quedan_en_catalogo_y_mapa(self):
        catalogo = self.service.catalogos()
        mapa = self.service.mapa_posiciones()

        self.assertIn("PISO PLANTA1", catalogo["ubicaciones"])
        self.assertIn("PISO PLANTA2", catalogo["ubicaciones"])
        self.assertEqual(mapa["PISO PLANTA1"]["cantidad"], 0)
        self.assertEqual(mapa["PISO PLANTA2"]["cantidad"], 0)

    def test_posicion_peligrosa_guarda_y_retorna_titulo_y_color(self):
        self.guardar(posicion="1A", producto="Otro", presentacion="Otra")
        posicion = self.service.actualizar_peligro_posicion(
            "1A", True, "Material inflamable", None,
        )
        self.assertEqual(posicion, {
            "codigo": "1A",
            "peligrosa": True,
            "tituloPeligro": "Material inflamable",
        })
        self.assertTrue(self.service.mapa_posiciones()["1A"]["peligrosa"])
        self.assertEqual(self.service.mapa_posiciones()["1A"]["tituloPeligro"], "Material inflamable")
        self.assertEqual(self.service.mapa_posiciones()["1A"]["materiaPrimaTotal"], 2)

        with self.assertRaisesRegex(ValueError, "título"):
            self.service.actualizar_peligro_posicion("1A", True, "", None)
        with self.assertRaisesRegex(LookupError, "no existe"):
            self.service.actualizar_peligro_posicion("99Z", True, "Peligro", None)

        retirada = self.service.actualizar_peligro_posicion("1A", False, "", None)
        self.assertFalse(retirada["peligrosa"])
        self.assertEqual(retirada["tituloPeligro"], "")

    def test_migracion_agrega_campos_de_peligro_a_ubicaciones_existentes(self):
        legacy_path = Path(self.temp_dir.name) / "legacy_locations.db"
        engine = create_engine(f"sqlite:///{legacy_path}")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE ubicaciones (id INTEGER PRIMARY KEY, codigo VARCHAR(20) UNIQUE, "
                "fila INTEGER, columna VARCHAR(2), activo BOOLEAN)"
            ))
            connection.execute(text(
                "INSERT INTO ubicaciones (codigo, fila, columna, activo) VALUES ('1A', 1, 'A', 1)"
            ))
        engine.dispose()

        legacy_factory = inicializar_base(f"sqlite:///{legacy_path}")
        try:
            legacy_service = InventarioService(legacy_factory)
            self.assertFalse(legacy_service.mapa_posiciones()["1A"]["peligrosa"])
            self.assertEqual(legacy_service.mapa_posiciones()["1A"]["tituloPeligro"], "")
            legacy_service.actualizar_peligro_posicion("1A", True, "Alerta", None)
            self.assertTrue(legacy_service.mapa_posiciones()["1A"]["peligrosa"])
        finally:
            legacy_factory.kw["bind"].dispose()

    def test_editar_ingreso_no_cuenta_doble_en_capacidad(self):
        creado = self.guardar(cantidad=5)
        editado = self.service.guardar_movimiento({**self.movimiento(cantidad=4), "id": creado["id"]}, None)
        self.assertEqual(editado["cantidad"], 4)

    def test_salida_sin_stock_es_rechazada(self):
        self.guardar(cantidad=2)
        with self.assertRaisesRegex(ValueError, "Stock insuficiente"):
            self.guardar(mvto="Salida", cantidad=3)

    def test_no_se_elimina_ingreso_con_salidas_posteriores(self):
        ingreso = self.guardar(cantidad=2)
        self.guardar(mvto="Salida", cantidad=2)
        with self.assertRaisesRegex(ValueError, "Stock insuficiente"):
            self.service.eliminar(ingreso["id"], None)

    def test_lote_que_salio_no_vuelve_a_ingresar(self):
        self.guardar(cantidad=1)
        self.guardar(mvto="Salida", cantidad=1)
        with self.assertRaisesRegex(ValueError, "ya registró una salida"):
            self.guardar(posicion="3C", cantidad=1)

    def test_traslado_mueve_stock_y_elimina_en_conjunto(self):
        self.guardar(cantidad=2)
        traslado = self.service.guardar_traslado(self.movimiento(posicionDestino="2B", cantidad=1), None)
        self.assertEqual(len(traslado), 2)
        stock = {(row["posicion"], row["cantidad"]) for row in self.service.stock()}
        self.assertEqual(stock, {("1A", 1), ("2B", 1)})
        # Un traslado no cuenta como salida de bodega: el lote puede seguir ingresando.
        self.guardar(posicion="3C", cantidad=1)
        self.service.eliminar(traslado[0]["id"], None)
        self.assertEqual(len(self.service.listar()), 2)

    def test_traslado_no_se_edita_como_movimiento(self):
        self.guardar(cantidad=2)
        traslado = self.service.guardar_traslado(self.movimiento(posicionDestino="2B", cantidad=1), None)
        with self.assertRaisesRegex(ValueError, "no se editan"):
            self.service.guardar_movimiento({**self.movimiento(), "id": traslado[1]["id"]}, None)

    def test_posicion_se_normaliza_y_debe_existir(self):
        self.assertEqual(self.guardar(posicion="a12")["posicion"], "12A")
        self.assertEqual(Movimiento.normalizar_posicion("12-c"), "12C")
        with self.assertRaisesRegex(ValueError, "no existe"):
            self.guardar(posicion="99Z")

    def test_producto_debe_estar_en_catalogo(self):
        with self.assertRaisesRegex(ValueError, "no está registrado"):
            self.guardar(producto="Cobre")
        self.service.crear_producto("Cobre", "materia_prima", None)
        self.assertEqual(self.guardar(producto="cobre")["producto"], "Cobre")

    def test_catalogo_y_creacion_de_producto_incluyen_categoria(self):
        productos = {p["nombre"]: p["categoria"] for p in self.service.catalogos()["productos"]}
        self.assertEqual(productos["Aluminio"], "producto_terminado")
        self.assertEqual(productos["Magnesio"], "producto_terminado")
        self.assertEqual(productos["Otro"], "materia_prima")

        with self.assertRaisesRegex(ValueError, "categoría"):
            self.service.crear_producto("Cobre", "sin_categoria", None)
        creado = self.service.crear_producto("Cobre", "materia_prima", None)
        self.assertEqual(creado["categoria"], "materia_prima")

    def test_migracion_clasifica_productos_existentes_sin_categoria(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        engine = create_engine(f"sqlite:///{legacy_path}")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE productos (id INTEGER PRIMARY KEY, nombre VARCHAR(60) UNIQUE, "
                "activo BOOLEAN, creado_en DATETIME)"
            ))
            connection.execute(text(
                "INSERT INTO productos (nombre, activo) VALUES "
                "('Aluminio', 1), ('Magnesio', 1), ('Otro', 1)"
            ))
        engine.dispose()

        legacy_factory = inicializar_base(f"sqlite:///{legacy_path}")
        try:
            with legacy_factory() as session:
                from backend.models import Producto
                productos = {p.nombre: p.categoria for p in session.query(Producto).all()}
            self.assertEqual(productos, {
                "Aluminio": "producto_terminado",
                "Magnesio": "producto_terminado",
                "Otro": "materia_prima",
            })
        finally:
            legacy_factory.kw["bind"].dispose()

    def test_importar_acepta_validos_y_reporta_rechazados(self):
        resultado = self.service.importar([
            self.movimiento(mvto="Salida", cantidad=1, fecha="2026-01-02"),
            self.movimiento(cantidad=2),
            self.movimiento(producto="Inexistente"),
        ], None)
        self.assertEqual(resultado["importados"], 2)
        self.assertEqual(resultado["rechazados"], 1)
        self.assertTrue(any("Registro 3" in error for error in resultado["errores"]))
        self.assertEqual({fila["indice"] for fila in resultado["fallidos"]}, {2})

    def test_lote_de_importacion_sin_validos_devuelve_detalle(self):
        resultado = self.service.importar([self.movimiento(posicion="99Z"), self.movimiento(cantidad=0)], None)
        self.assertEqual((resultado["importados"], resultado["rechazados"]), (0, 2))
        self.assertEqual([f["indice"] for f in resultado["fallidos"]], [0, 1])
        self.assertIn("no existe", resultado["fallidos"][0]["error"])

    def test_restaurar_reemplaza_y_completa_catalogos(self):
        self.guardar()
        self.service.crear_producto("Zinc", "materia_prima", None)
        resultado = self.service.restaurar([
            {**self.movimiento(producto="Zinc", posicion="PATIO"), "id": 7},
            self.movimiento(cantidad=0),
        ], None)
        self.assertEqual((resultado["importados"], resultado["rechazados"]), (1, 1))
        movimientos = self.service.listar()
        self.assertEqual(len(movimientos), 1)
        self.assertEqual((movimientos[0]["producto"], movimientos[0]["posicion"]), ("Zinc", "PATIO"))

    def test_auditoria_registra_operaciones(self):
        self.guardar()
        self.assertEqual(self.service.auditoria()[0]["accion"], "movimiento.crear")
        movimiento = self.service.listar()[0]
        self.assertTrue(movimiento["creadoEn"])


if __name__ == "__main__":
    unittest.main()
