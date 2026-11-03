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
        this.mapaPosiciones = {};
        this.estadosLote = new Map();
        this.catalogos = { productos: [], presentaciones: [], ubicaciones: [] };
    }

    async cargarCatalogos() {
        this.catalogos = await request('/catalogos');
        return this.catalogos;
    }

    async crearProducto(nombre, categoria) {
        await request('/catalogos/productos', { method: 'POST', body: JSON.stringify({ nombre, categoria }) });
        return this.cargarCatalogos();
    }

    async actualizarProducto(id, cambios) {
        await request(`/catalogos/productos/${id}`, {
            method: 'PATCH',
            body: JSON.stringify(cambios)
        });
        return this.cargarCatalogos();
    }

    async eliminarProducto(id) {
        await request(`/catalogos/productos/${id}`, { method: 'DELETE' });
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
        const [data, mapaPosiciones] = await Promise.all([
            request('/movimientos'),
            request('/posiciones')
        ]);
        this.movimientos = data.map(item => new Movimiento(item));
        this.mapaPosiciones = mapaPosiciones;
        await this.cargarEstadosLotes();
        return this.movimientos;
    }

    async cargarEstadosLotes() {
        const estados = await request('/lotes/estados');
        this.estadosLote = new Map(estados.map(item => [
            this.claveLote(item.producto, item.lote),
            item
        ]));
        return this.estadosLote;
    }

    claveLote(producto, lote) {
        return JSON.stringify([producto, lote]);
    }

    async actualizarEstadoLote(producto, lote, estado) {
        await request('/lotes/estado', {
            method: 'PATCH',
            body: JSON.stringify({ producto, lote, estado })
        });
        await this.cargarEstadosLotes();
    }

    async actualizarPeligroPosicion(codigo, peligrosa, titulo) {
        await request(`/posiciones/${encodeURIComponent(codigo)}/peligro`, {
            method: 'PATCH',
            body: JSON.stringify({ peligrosa, titulo })
        });
        await this.cargarDatos();
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

    // Envía un lote del Excel. No recarga los datos: el controlador lo hace al terminar todos los lotes.
    async importarLote(registros) {
        return request('/importar', {
            method: 'POST',
            body: JSON.stringify({ registros })
        });
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
        const categorias = new Map(this.catalogos.productos.map(producto => [producto.nombre, producto.categoria]));
        this.movimientos.forEach(item => {
            if (item.Factor === 0) return;
            const key = `${item.posicion}||${item.producto}||${item.presentacion}||${item.lote}`;
            stockMap[key] ||= {
                posicion: item.posicion,
                producto: item.producto,
                categoria: categorias.get(item.producto),
                estadoLote: this.estadosLote.get(this.claveLote(item.producto, item.lote)),
                presentacion: item.presentacion,
                lote: item.lote,
                cantidad: 0
            };
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
        return this.mapaPosiciones;
    }
}
