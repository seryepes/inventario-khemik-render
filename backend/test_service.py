import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path

from .service import InventarioService
from .domain import Movimiento
from repository import SQLiteInventarioRepository


class InventarioServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = InventarioService(Path(self.temp_dir.name) / "test.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def movimiento(self, **changes):
        data = {"fecha": "2026-01-01", "mvto": "Ingreso", "posicion": "1A", "producto": "Aluminio", "presentacion": "125 kg", "lote": "L-1", "cantidad": 2}
        data.update(changes)
        return data

    def test_ingreso_y_stock(self):
        self.service.guardar_movimiento(self.movimiento())
        self.assertEqual(self.service.stock()[0]["cantidad"], 2)

    def test_posiciones_de_piso_disponibles_en_mapa(self):
        mapa = self.service.mapa_posiciones()

        self.assertIn("PISO PLANTA1", mapa)
        self.assertIn("PISO PLANTA2", mapa)
        self.assertEqual(mapa["PISO PLANTA1"]["cantidad"], 0)
        self.assertEqual(mapa["PISO PLANTA2"]["cantidad"], 0)

    def test_capacidad_por_posicion(self):
        self.service.guardar_movimiento(self.movimiento(cantidad=5))
        with self.assertRaisesRegex(ValueError, "está llena"):
            self.service.guardar_movimiento(self.movimiento(lote="L-2", cantidad=1))

    def test_posicion_no_acepta_otro_producto_y_permite_la_misma_clase(self):
        posicion = "Piso Planta1"
        self.service.guardar_movimiento(self.movimiento(posicion=posicion))
        mismo_producto = self.movimiento(posicion=posicion, lote="L-2", cantidad=1)
        self.service.guardar_movimiento(mismo_producto)

        with self.assertRaisesRegex(ValueError, "está ocupada por Aluminio"):
            self.service.guardar_movimiento(
                self.movimiento(posicion=posicion, producto="Magnesio", lote="M-1")
            )

    def test_traslado_no_permite_ingresar_producto_a_posicion_ocupada(self):
        self.service.guardar_movimiento(self.movimiento(posicion="ORIGEN"))
        self.service.guardar_movimiento(
            self.movimiento(posicion="PISO PLANTA2", producto="Magnesio", lote="M-1")
        )

        with self.assertRaisesRegex(ValueError, "está ocupada por Magnesio"):
            self.service.guardar_traslado(
                self.movimiento(posicion="ORIGEN", posicionDestino="Piso Planta2", cantidad=1)
            )

    def test_importacion_rechaza_otro_producto_en_posicion_ocupada(self):
        resultado = self.service.importar([
            self.movimiento(posicion="PISO PLANTA1"),
            self.movimiento(posicion="PISO PLANTA1", producto="Magnesio", lote="M-1"),
        ])

        self.assertEqual(resultado, {"importados": 1, "rechazados": 1})

    def test_fecha_y_hora_de_registro_se_guardan_y_no_cambian_al_editar(self):
        creado = self.service.guardar_movimiento(self.movimiento())
        registrado_en = creado.registrado_en
        self.assertIsNotNone(registrado_en)
        self.assertIn("T", registrado_en)

        actualizado = self.service.guardar_movimiento(
            self.movimiento(id=creado.id, cantidad=3)
        )

        self.assertEqual(actualizado.registrado_en, registrado_en)
        self.assertEqual(self.service.listar()[0].registrado_en, registrado_en)

    def test_migracion_de_registros_anteriores_deja_hora_desconocida(self):
        old_database = Path(self.temp_dir.name) / "old.db"
        with closing(sqlite3.connect(old_database)) as db:
            db.execute("""
                CREATE TABLE movimientos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT NOT NULL, mvto TEXT NOT NULL, posicion TEXT NOT NULL,
                    producto TEXT NOT NULL, presentacion TEXT NOT NULL, lote TEXT NOT NULL,
                    cantidad INTEGER NOT NULL, observaciones TEXT NOT NULL DEFAULT '',
                    traslado_id TEXT, es_traslado INTEGER NOT NULL DEFAULT 0
                )
            """)
            db.execute(
                "INSERT INTO movimientos (fecha,mvto,posicion,producto,presentacion,lote,cantidad) "
                "VALUES ('2026-01-01','Ingreso','1A','Aluminio','125 kg','L-1',1)"
            )
            db.commit()

        repository = SQLiteInventarioRepository(old_database)

        self.assertIsNone(repository.listar()[0].registrado_en)

    def test_traslado_mueve_stock_y_elimina_en_conjunto(self):
        self.service.guardar_movimiento(self.movimiento(cantidad=2))
        traslado = self.service.guardar_traslado(self.movimiento(posicionDestino="2B", cantidad=1))
        self.assertEqual(len(traslado), 2)
        stock = {(row["posicion"], row["cantidad"]) for row in self.service.stock()}
        self.assertIn(("1A", 1), stock)
        self.assertIn(("2B", 1), stock)
        self.service.eliminar(traslado[0].id)
        self.assertEqual(len(self.service.listar()), 1)

    def test_servir_archivos_estaticos_js(self):
        from .app import app

        client = app.test_client()
        response = client.get('/servicios/service.js')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'export class InventarioService', response.data)
        self.assertEqual(response.mimetype, 'text/javascript')

    def test_repositorio_migra_base_anterior_conservando_datos(self):
        legacy_path = Path(self.temp_dir.name) / "inventario.db"
        database_path = Path(self.temp_dir.name) / "repository" / "inventario.db"
        legacy_repository = SQLiteInventarioRepository(legacy_path)
        legacy_repository.guardar(Movimiento.from_dict(self.movimiento()))

        repository = SQLiteInventarioRepository(database_path, legacy_database_path=legacy_path)

        self.assertFalse(legacy_path.exists())
        movimientos = repository.listar()
        self.assertEqual(len(movimientos), 1)
        self.assertEqual(movimientos[0].lote, "L-1")


if __name__ == "__main__":
    unittest.main()
