import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import { InventarioService } from '../frontend/js/servicio.js';
import { Movimiento } from '../frontend/js/movimiento.js';

test('las tarjetas suman existencias actuales y desglosan las presentaciones', () => {
    const service = new InventarioService();
    service.catalogos.productos = [
        { nombre: 'Aluminio', categoria: 'producto_terminado' },
        { nombre: 'Hidróxido de aluminio', categoria: 'producto_terminado' },
        { nombre: 'Hidroxido de magnesio', categoria: 'producto_terminado' },
        { nombre: 'Vacunas', categoria: 'materia_prima' },
        { nombre: 'Otro producto', categoria: 'producto_terminado' }
    ];
    const movimiento = (producto, presentacion, cantidad, mvto = 'Ingreso', posicion = '1A') =>
        new Movimiento({ producto, presentacion, cantidad, mvto, posicion, lote: 'L1' });
    service.movimientos = [
        movimiento('Aluminio', '125 kg', 10),
        movimiento('Aluminio', '125 kg', 3, 'Salida'),
        movimiento('Hidróxido de aluminio', 'Otra', 4),
        movimiento('Hidróxido de aluminio', '50 kg', 2),
        movimiento('Hidroxido de magnesio', '200 kg', 6),
        movimiento('Vacunas', 'Caja', 9),
        movimiento('Vacunas', 'Caja', 2, 'Salida'),
        movimiento('Otro producto', 'Caja', 5),
        movimiento('Otro producto', 'Caja', 5, 'Salida')
    ];

    assert.deepEqual(service.obtenerEstadisticasStock(), {
        aluminio: { total: 13, presentaciones: { '125 kg': 7, '200 kg': 0, '50 kg': 2 } },
        magnesio: { total: 6, presentaciones: { '125 kg': 0, '200 kg': 6 } },
        vacunas: 7,
        terminado: 19
    });
});

test('los traslados no duplican existencias y las categorías se actualizan', () => {
    const service = new InventarioService();
    service.catalogos.productos = [{ nombre: 'Magnesio', categoria: 'producto_terminado' }];
    service.movimientos = [
        new Movimiento({ producto: 'Magnesio', presentacion: '125 kg', cantidad: 8, mvto: 'Ingreso', posicion: '1A', lote: 'L1' }),
        new Movimiento({ producto: 'Magnesio', presentacion: '125 kg', cantidad: 3, mvto: 'Salida', posicion: '1A', lote: 'L1', esTraslado: true }),
        new Movimiento({ producto: 'Magnesio', presentacion: '125 kg', cantidad: 3, mvto: 'Ingreso', posicion: '2A', lote: 'L1', esTraslado: true })
    ];
    assert.equal(service.obtenerEstadisticasStock().magnesio.total, 8);
    assert.equal(service.obtenerEstadisticasStock().terminado, 8);
    service.catalogos.productos[0].categoria = 'materia_prima';
    assert.equal(service.obtenerEstadisticasStock().terminado, 0);
});

test('el tablero muestra los totales y conserva las posiciones ocupadas', () => {
    const html = readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
    const controlador = readFileSync(new URL('../frontend/js/controlador.js', import.meta.url), 'utf8');
    const render = controlador.slice(controlador.indexOf('function renderEstadisticas() {'),
        controlador.indexOf('\nfunction renderStockConsolidado()'));
    const elementos = new Map();
    const document = {
        getElementById(id) {
            assert.ok(html.includes(`id="${id}"`), `Falta el elemento ${id}`);
            if (!elementos.has(id)) elementos.set(id, {});
            return elementos.get(id);
        }
    };
    const service = {
        obtenerEstadisticasStock: () => ({
            aluminio: { total: 9, presentaciones: { '125 kg': 5, '200 kg': 0 } },
            magnesio: { total: 2, presentaciones: { '125 kg': 0, '200 kg': 2 } },
            vacunas: 3,
            terminado: 11
        }),
        obtenerMapaPosiciones: () => ({ '1A': { cantidad: 4 }, '2A': { cantidad: 0 } }),
        movimientos: [{}, {}]
    };
    runInNewContext(`${render}\nrenderEstadisticas();`, { document, service });
    assert.equal(elementos.get('statAluminio').innerText, '9 un.');
    assert.equal(elementos.get('statAluminioDetalle').innerText, '125 kg: 5 · 200 kg: 0');
    assert.equal(elementos.get('statMagnesio').innerText, '2 un.');
    assert.equal(elementos.get('statVacunas').innerText, '3 un.');
    assert.equal(elementos.get('statTerminado').innerText, '11 un.');
    assert.equal(elementos.get('statPosiciones').innerText, '1');
});
