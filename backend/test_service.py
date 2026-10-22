import tempfile
import unittest
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

    def test_capacidad_por_posicion(self):
        self.service.guardar_movimiento(self.movimiento(cantidad=5))
        with self.assertRaisesRegex(ValueError, "está llena"):
            self.service.guardar_movimiento(self.movimiento(lote="L-2", cantidad=1))

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
