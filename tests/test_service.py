import tempfile
import unittest
from pathlib import Path

from backend.database import inicializar_base
from backend.domain import Movimiento
from backend.service import InventarioService


class InventarioServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        session_factory = inicializar_base(f"sqlite:///{Path(self.temp_dir.name) / 'test.db'}")
        self.service = InventarioService(session_factory)

    def tearDown(self):
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
        self.service.crear_producto("Cobre", None)
        self.assertEqual(self.guardar(producto="cobre")["producto"], "Cobre")

    def test_importar_acepta_validos_y_reporta_rechazados(self):
        resultado = self.service.importar([
            self.movimiento(mvto="Salida", cantidad=1, fecha="2026-01-02"),
            self.movimiento(cantidad=2),
            self.movimiento(producto="Inexistente"),
        ], None)
        self.assertEqual(resultado["importados"], 2)
        self.assertEqual(resultado["rechazados"], 1)
        self.assertIn("Registro 3", resultado["errores"][0])
        self.assertEqual(resultado["fallidos"][0]["indice"], 2)

    def test_lote_de_importacion_sin_validos_devuelve_detalle(self):
        resultado = self.service.importar([self.movimiento(posicion="99Z"), self.movimiento(cantidad=0)], None)
        self.assertEqual((resultado["importados"], resultado["rechazados"]), (0, 2))
        self.assertEqual([f["indice"] for f in resultado["fallidos"]], [0, 1])
        self.assertIn("no existe", resultado["fallidos"][0]["error"])

    def test_restaurar_reemplaza_y_completa_catalogos(self):
        self.guardar()
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


if __name__ == "__main__":
    unittest.main()
