export class Movimiento {
    constructor({ id = null, fecha, mvto, posicion = 'Sin Ubicar', posicionDestino = '', producto = 'Otro', presentacion = 'Otra', lote = '-', cantidad = 0, observaciones = '', trasladoId = null, esTraslado = false }) {
        this.id = id ? parseInt(id) : null;
        this.fecha = fecha || new Date().toISOString().split('T')[0];
        this.mvto = Movimiento.normalizarMovimiento(mvto);
        this.posicion = Movimiento.normalizarPosicion(posicion);
        this.posicionDestino = posicionDestino ? Movimiento.normalizarPosicion(posicionDestino) : '';
        this.producto = producto || 'Otro';
        this.presentacion = Movimiento.normalizarPresentacion(presentacion);
        this.lote = lote ? lote.toString().trim() : '-';
        this.cantidad = parseInt(cantidad) || 0;
        this.observaciones = observaciones ? observaciones.toString().trim() : '';
        this.trasladoId = trasladoId || null;
        this.esTraslado = Boolean(esTraslado);
    }

    static normalizarPresentacion(presentacion) {
        const valor = (presentacion || '').toString().trim().toLowerCase().replace(/\s+/g, '');
        if (valor === '125g' || valor === '0.125kg' || valor === '125kg') return '125 kg';
        if (valor === '200kg') return '200 kg';
        return presentacion ? presentacion.toString().trim() : 'Otra';
    }

    static normalizarMovimiento(mvto) {
        const valor = (mvto || '').toString().trim().toLowerCase();
        if (valor === 'ingreso') return 'Ingreso';
        if (valor === 'salida') return 'Salida';
        if (valor === 'traslado') return 'Traslado';
        if (valor === 'sin ubicar') return 'Sin ubicar';
        return mvto || 'Ingreso';
    }

    static normalizarPosicion(posicion) {
        return posicion ? posicion.toString().toUpperCase().trim() : 'Sin Ubicar';
    }

    get Factor() {
        if (this.mvto === 'Ingreso') return 1;
        if (this.mvto === 'Salida') return -1;
        return 0;
    }

    get FechaFormateada() {
        if (!this.fecha) return '-';
        const soloFecha = this.fecha.toString().split('T')[0].split(' ')[0];
        const partes = soloFecha.split('-');
        if (partes.length !== 3) return this.fecha;
        const [anio, mes, dia] = partes;
        return `${dia.padStart(2, '0')}/${mes.padStart(2, '0')}/${anio}`;
    }
}