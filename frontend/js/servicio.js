import { Movimiento } from './movimiento.js?v=3';

const API = '/api';

async function request(path, options = {}) {
    const response = await fetch(`${API}${path}`, {
        ...options,
        credentials: 'same-origin',
        // X-Khemik-Request es la protección CSRF que exige el backend en toda escritura.
        headers: { 'Content-Type': 'application/json', 'X-Khemik-Request': '1', ...(options.headers || {}) }
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && !path.startsWith('/auth/')) {
        // La sesión expiró: se recarga para mostrar la pantalla de acceso.
        window.location.reload();
    }
    if (!response.ok) throw new Error(body.error || `Error HTTP ${response.status}`);
    return body;
}

export class InventarioService {
    constructor() {
        this.movimientos = [];
        this.catalogos = { productos: [], presentaciones: [], ubicaciones: [] };
    }

    async cargarCatalogos() {
        this.catalogos = await request('/catalogos');
        return this.catalogos;
    }

    async crearProducto(nombre) {
        await request('/catalogos/productos', { method: 'POST', body: JSON.stringify({ nombre }) });
        return this.cargarCatalogos();
    }

    async crearPresentacion(nombre, capacidad) {
        await request('/catalogos/presentaciones', { method: 'POST', body: JSON.stringify({ nombre, capacidad }) });
        return this.cargarCatalogos();
    }

    async actualizarUsuario(username, cambios) {
        return request(`/auth/users/${encodeURIComponent(username)}`, {
            method: 'PATCH',
            body: JSON.stringify(cambios)
        });
    }

    async authStatus() {
        return request('/auth/status');
    }

    async iniciarSesion(username, password, setup = false) {
        return request(setup ? '/auth/setup' : '/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username, password })
        });
    }

    async cerrarSesion() {
        return request('/auth/logout', { method: 'POST' });
    }

    async listarUsuarios() {
        return request('/auth/users');
    }

    async crearUsuario(username, password, role) {
        return request('/auth/users', {
            method: 'POST',
            body: JSON.stringify({ username, password, role })
        });
    }

    async cargarDatos() {
        const data = await request('/movimientos');
        this.movimientos = data.map(item => new Movimiento(item));
        return this.movimientos;
    }

    async guardarMovimiento(datos) {
        const id = datos.id ? `/${datos.id}` : '';
        await request(`/movimientos${id}`, {
            method: datos.id ? 'PUT' : 'POST',
            body: JSON.stringify(datos)
        });
        await this.cargarDatos();
    }

    async guardarTraslado(datos) {
        await request('/traslados', { method: 'POST', body: JSON.stringify(datos) });
        await this.cargarDatos();
    }

    async eliminarRegistro(id) {
        await request(`/movimientos/${id}`, { method: 'DELETE' });
        await this.cargarDatos();
    }

    async borrarTodo() {
        await request('/movimientos', { method: 'DELETE' });
        await this.cargarDatos();
    }

    async importarDesdeExcel(registros) {
        const resultado = await request('/importar', {
            method: 'POST',
            body: JSON.stringify({ registros })
        });
        await this.cargarDatos();
        return resultado;
    }

    async restaurarDesdeJSON(registros) {
        const resultado = await request('/restaurar', {
            method: 'POST',
            body: JSON.stringify({ registros })
        });
        await this.cargarDatos();
        return resultado;
    }

    filtrarMovimientos({ busqueda = '', producto = '', presentacion = '', mvto = '' }) {
        const search = busqueda.toLowerCase().trim();
        return this.movimientos.filter(item => {
            const matchSearch = item.lote.toLowerCase().includes(search) ||
                item.posicion.toLowerCase().includes(search) ||
                item.producto.toLowerCase().includes(search) ||
                (item.id && item.id.toString().includes(search)) ||
                item.observaciones.toLowerCase().includes(search);
            return matchSearch && (!producto || item.producto === producto) &&
                (!presentacion || item.presentacion === presentacion) &&
                (!mvto || item.mvto === mvto);
        });
    }

    obtenerStockConsolidado() {
        const stockMap = {};
        this.movimientos.forEach(item => {
            if (item.Factor === 0) return;
            const key = `${item.posicion}||${item.producto}||${item.presentacion}||${item.lote}`;
            stockMap[key] ||= { posicion: item.posicion, producto: item.producto, presentacion: item.presentacion, lote: item.lote, cantidad: 0 };
            stockMap[key].cantidad += item.cantidad * item.Factor;
        });
        return Object.values(stockMap).filter(item => item.cantidad > 0);
    }

    obtenerEstadisticasIngresos() {
        const ingresos = {
            Aluminio: { '125 kg': 0, '200 kg': 0, Otra: 0 },
            Magnesio: { '125 kg': 0, '200 kg': 0, Otra: 0 }
        };
        this.movimientos.forEach(item => {
            if (item.mvto !== 'Ingreso' || !ingresos[item.producto]) return;
            const pres = item.presentacion.includes('125') ? '125 kg' : item.presentacion.includes('200') ? '200 kg' : 'Otra';
            ingresos[item.producto][pres] += item.cantidad;
        });
        return ingresos;
    }

    obtenerMapaPosiciones() {
        const posiciones = {};
        this.movimientos.forEach(item => {
            if (!item.posicion || item.posicion.toUpperCase() === 'SIN UBICAR' || item.Factor === 0) return;
            posiciones[item.posicion] ||= { cantidad: 0, aluminioTotal: 0, magnesioTotal: 0, otroTotal: 0 };
            const cantidad = item.cantidad * item.Factor;
            const posicion = posiciones[item.posicion];
            posicion.cantidad += cantidad;
            if (item.producto === 'Aluminio') posicion.aluminioTotal += cantidad;
            else if (item.producto === 'Magnesio') posicion.magnesioTotal += cantidad;
            else posicion.otroTotal += cantidad;
        });
        return posiciones;
    }
}
