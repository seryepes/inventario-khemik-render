import { InventarioService } from '../servicios/service.js?v=2';

// Instanciación directa del servicio local (sin credenciales ni red)
const service = new InventarioService();

let currentPage = 1;
const pageSize = 15;
let modalRegistro;
let modalProductos;

document.addEventListener("DOMContentLoaded", async () => {
    modalRegistro = new bootstrap.Modal(document.getElementById('modalRegistro'));
    modalProductos = new bootstrap.Modal(document.getElementById('modalProductosPosicion'));

    listeners();
    await cargarAplicacion();
});

function listeners() {
    ['searchInput', 'filterProduct', 'filterPres', 'filterMvto'].forEach(id => {
        document.getElementById(id).addEventListener('change', () => { currentPage = 1; renderTabla(); });
        document.getElementById(id).addEventListener('input', () => { currentPage = 1; renderTabla(); });
    });

    document.getElementById('excelFileInput').addEventListener('change', leerExcel);
    document.getElementById('backupFileInput').addEventListener('change', importarBackupJSON);
    document.getElementById('inventoryForm').addEventListener('submit', guardarRegistro);
    document.getElementById('formMvto').addEventListener('change', actualizarCamposTraslado);
    document.getElementById('btnExportarExcel').addEventListener('click', exportarExcel);
    document.getElementById('btnExportarCSV').addEventListener('click', exportarCSV);
    document.getElementById('btnBackupJson').addEventListener('click', exportarBackupJSON);
    document.getElementById('btnBorrarTodo').addEventListener('click', borrarTodo);
    document.getElementById('btnNuevoRegistro').addEventListener('click', prepararNuevoRegistro);
    document.getElementById('stockSearchInput').addEventListener('input', renderStockConsolidado);
    document.getElementById('stockFilterProduct').addEventListener('change', renderStockConsolidado);

    document.getElementById('tab-stock-tab').addEventListener('click', () => renderStockConsolidado());
    document.getElementById('tab-posiciones-tab').addEventListener('click', () => renderMapaPosiciones());
}

async function cargarAplicacion() {
    try {
        await service.cargarDatos();
        actualizarEstadoGeneral();
    } catch (e) {
        alert("Error cargando inventario: " + e.message);
    }
}

function actualizarEstadoGeneral() {
    renderTabla();
    renderEstadisticas();
    renderStockConsolidado();
    renderMapaPosiciones();
}

function renderTabla() {
    const filtros = {
        busqueda: document.getElementById('searchInput').value,
        producto: document.getElementById('filterProduct').value,
        presentacion: document.getElementById('filterPres').value,
        mvto: document.getElementById('filterMvto').value
    };

    const filtrados = service.filtrarMovimientos(filtros);
    const totalPages = Math.ceil(filtrados.length / pageSize) || 1;
    if (currentPage > totalPages) currentPage = totalPages;

    const startIdx = (currentPage - 1) * pageSize;
    const pageData = filtrados.slice(startIdx, startIdx + pageSize);

    const tbody = document.getElementById('tableBody');
    tbody.innerHTML = '';
    document.getElementById('totalRecordsBadge').innerText = `${filtrados.length} registros`;

    if (pageData.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-4">No se encontraron registros.</td></tr>`;
    } else {
        pageData.forEach(item => {
            const tr = document.createElement('tr');
            let badgeClass = item.mvto === 'Ingreso' ? 'bg-success' : (item.mvto === 'Salida' ? 'bg-danger' : 'bg-dark');
            
            tr.innerHTML = `
                <td class="fw-bold text-muted">#${item.id}</td>
                <td class="small">${item.FechaFormateada}</td>
                <td><span class="badge ${badgeClass} badge-pos">${item.mvto}</span></td>
                <td><span class="badge bg-light text-dark border fw-bold">${item.posicion}</span></td>
                <td class="fw-semibold">${item.producto}</td>
                <td><span class="badge bg-light text-muted border">${item.presentacion}</span></td>
                <td><code>${item.lote}</code></td>
                <td class="fw-bold">${item.cantidad}</td>
                <td class="small text-muted">${item.observaciones || '-'}</td>
                <td class="text-center">
                    <button class="btn btn-sm btn-outline-primary me-1 btn-edit" data-id="${item.id}"><i class="fa-solid fa-pen"></i></button>
                    <button class="btn btn-sm btn-outline-danger btn-delete" data-id="${item.id}"><i class="fa-solid fa-trash"></i></button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        document.querySelectorAll('.btn-edit').forEach(b => b.addEventListener('click', (e) => editarRegistro(e.currentTarget.dataset.id)));
        document.querySelectorAll('.btn-delete').forEach(b => b.addEventListener('click', (e) => eliminarRegistro(e.currentTarget.dataset.id)));
    }

    const sumaPagina = pageData.reduce((acc, i) => acc + i.cantidad, 0);
    document.getElementById('totalCantidadPagina').innerText = sumaPagina;
    const stockFiltrado = obtenerStockFiltrado();
    const totalStockFiltrado = stockFiltrado.reduce((acc, item) => acc + item.cantidad, 0);
    document.getElementById('statTotalMov').innerText = totalStockFiltrado;
    document.getElementById('statTotalMovDetalle').innerText = `${stockFiltrado.length} productos con stock`;

    renderPaginacion(totalPages, filtrados.length);
}

function obtenerStockFiltrado() {
    const search = document.getElementById('searchInput').value.toLowerCase().trim();
    const producto = document.getElementById('filterProduct').value;
    const presentacion = document.getElementById('filterPres').value;

    return service.obtenerStockConsolidado().filter(item => {
        const matchSearch = item.lote.toLowerCase().includes(search) ||
            item.posicion.toLowerCase().includes(search) ||
            item.producto.toLowerCase().includes(search);
        const matchProducto = !producto || item.producto === producto;
        const matchPresentacion = !presentacion || item.presentacion === presentacion;
        return matchSearch && matchProducto && matchPresentacion;
    });
}

function renderPaginacion(totalPages, totalFiltered) {
    document.getElementById('pageInfo').innerText = `Página ${currentPage} de ${totalPages} (${totalFiltered} registros)`;
    const pagination = document.getElementById('pagination');
    pagination.innerHTML = '';

    const createLi = (text, page, disabled = false, active = false) => {
        const li = document.createElement('li');
        li.className = `page-item ${disabled ? 'disabled' : ''} ${active ? 'active' : ''}`;
        li.innerHTML = `<a class="page-link" href="#">${text}</a>`;
        if (!disabled && !active) li.addEventListener('click', (e) => { e.preventDefault(); currentPage = page; renderTabla(); });
        return li;
    };

    pagination.appendChild(createLi('«', currentPage - 1, currentPage === 1));
    let start = Math.max(1, currentPage - 2);
    let end = Math.min(totalPages, start + 4);
    for (let i = start; i <= end; i++) {
        pagination.appendChild(createLi(i, i, false, i === currentPage));
    }
    pagination.appendChild(createLi('»', currentPage + 1, currentPage === totalPages));
}

function renderEstadisticas() {
    const ing = service.obtenerEstadisticasIngresos();
    const mapPos = service.obtenerMapaPosiciones();
    const posOcupadas = Object.values(mapPos).filter(p => p.cantidad > 0).length;

    const sumAlu = ing.Aluminio['125 kg'] + ing.Aluminio['200 kg'] + ing.Aluminio['Otra'];
    const sumMag = ing.Magnesio['125 kg'] + ing.Magnesio['200 kg'] + ing.Magnesio['Otra'];

    document.getElementById('statAluminio').innerText = `${sumAlu} un.`;
    document.getElementById('statAluminioDetalle').innerText = `125 kg: ${ing.Aluminio['125 kg']} · 200 kg: ${ing.Aluminio['200 kg']} · Otra: ${ing.Aluminio['Otra']}`;
    
    document.getElementById('statMagnesio').innerText = `${sumMag} un.`;
    document.getElementById('statMagnesioDetalle').innerText = `125 kg: ${ing.Magnesio['125 kg']} · 200 kg: ${ing.Magnesio['200 kg']} · Otra: ${ing.Magnesio['Otra']}`;
    
    document.getElementById('statPosiciones').innerText = `${posOcupadas}`;
    document.getElementById('totalCargadosBadge').innerHTML = `<i class="fa-solid fa-circle-check me-1"></i>${service.movimientos.length} Registros`;
}

function renderStockConsolidado() {
    const stock = service.obtenerStockConsolidado();
    const txt = document.getElementById('stockSearchInput').value.toLowerCase().trim();
    const prod = document.getElementById('stockFilterProduct').value;

    let totAlu = 0, totMag = 0, totGen = 0;
    stock.forEach(s => {
        totGen += s.cantidad;
        if (s.producto === 'Aluminio') totAlu += s.cantidad;
        else if (s.producto === 'Magnesio') totMag += s.cantidad;
    });

    document.getElementById('stockTotalAluminio').innerText = `${totAlu} un.`;
    document.getElementById('stockTotalMagnesio').innerText = `${totMag} un.`;
    document.getElementById('stockTotalGeneral').innerText = `${totGen} un.`;

    const filtrados = stock.filter(s => {
        const matchTxt = s.posicion.toLowerCase().includes(txt) || s.producto.toLowerCase().includes(txt) || s.lote.toLowerCase().includes(txt);
        const matchProd = !prod || s.producto === prod;
        return matchTxt && matchProd;
    });

    const tbody = document.getElementById('stockTableBody');
    tbody.innerHTML = '';
    let totalFiltrado = 0;

    filtrados.forEach(s => {
        totalFiltrado += s.cantidad;
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><span class="badge bg-secondary">${s.posicion}</span></td>
            <td class="fw-semibold">${s.producto}</td>
            <td><span class="badge bg-light text-dark border">${s.presentacion}</span></td>
            <td><code>${s.lote}</code></td>
            <td class="text-end fw-bold text-success fs-6">${s.cantidad}</td>
        `;
        tbody.appendChild(tr);
    });

    document.getElementById('stockTableFooterTotal').innerText = totalFiltrado;
    document.getElementById('stockFiltradoBadge').innerText = `${totalFiltrado} un. en esta vista`;
}

function renderMapaPosiciones() {
    const mapPosData = service.obtenerMapaPosiciones();
    const mapContainer = document.getElementById('mapaPosiciones');
    mapContainer.innerHTML = '';

    for (let fila = 1; fila <= 44; fila++) {
        const filaDiv = document.createElement('div');
        filaDiv.className = 'grid-fila';
        filaDiv.style.cssText = 'display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-bottom: 12px; padding: 10px; background: #f8f9fa; border-radius: 8px;';

        const label = document.createElement('div');
        label.style.cssText = 'grid-column: 1 / -1; font-weight: bold; font-size: 14px; color: #495057; margin-bottom: 5px;';
        label.textContent = `Fila ${fila}`;
        filaDiv.appendChild(label);

        ['A', 'B', 'C', 'D', 'E', 'F'].forEach(col => {
            const posKey = `${fila}${col}`;
            const datos = mapPosData[posKey];
            const cantidad = datos ? Math.max(0, datos.cantidad) : 0;
            const estaOcupada = datos && cantidad > 0;

            const puestoDiv = document.createElement('div');
            puestoDiv.style.cssText = 'padding: 10px; border-radius: 6px; text-align: center; font-weight: 500; font-size: 12px; cursor: pointer; transition: all 0.2s ease; border: 2px solid transparent; line-height: 1.3;';

            if (estaOcupada) {
                const tieneAlu = datos.aluminioTotal > 0;
                const tieneMag = datos.magnesioTotal > 0;
                let colorBase = (tieneAlu && tieneMag) ? '#6f42c1' : (tieneAlu ? '#0d6efd' : (tieneMag ? '#fd7e14' : '#212529'));

                puestoDiv.style.backgroundColor = colorBase;
                puestoDiv.style.color = 'white';
                puestoDiv.innerHTML = `<div style="font-size: 12px; font-weight: bold;">✓ ${posKey}</div><div style="font-size: 10px; opacity: 0.9;">Total: ${cantidad}</div>`;
                puestoDiv.addEventListener('click', () => mostrarProductosPosicion(posKey));
            } else {
                puestoDiv.style.backgroundColor = '#ffffff';
                puestoDiv.style.color = '#6c757d';
                puestoDiv.style.border = '2px solid #dee2e6';
                puestoDiv.textContent = posKey;
            }
            filaDiv.appendChild(puestoDiv);
        });
        mapContainer.appendChild(filaDiv);
    }

    const ocupadas = Object.values(mapPosData).filter(d => d.cantidad > 0).length;
    document.getElementById('posOcupadas').textContent = ocupadas;
    document.getElementById('posDisponibles').textContent = 264 - ocupadas;
}

function mostrarProductosPosicion(posicion) {
    const stock = service.obtenerStockConsolidado().filter(s => s.posicion === posicion);
    document.getElementById('modalPosicionLabel').innerHTML = `<i class="fa-solid fa-box me-2"></i>Productos en Posición ${posicion}`;

    let html = '<div class="table-responsive"><table class="table table-hover align-middle"><thead class="table-light"><tr><th>Producto</th><th>Presentación</th><th>Lote</th><th class="text-end">Cantidad</th></tr></thead><tbody>';
    let total = 0;

    stock.forEach(p => {
        total += p.cantidad;
        html += `<tr><td>${p.producto}</td><td>${p.presentacion}</td><td><code>${p.lote}</code></td><td class="text-end fw-bold text-success">${p.cantidad} un.</td></tr>`;
    });

    html += `</tbody></table></div><div class="alert alert-info mt-3 mb-0"><strong>Total:</strong> ${total} unidades</div>`;
    document.getElementById('contenidoProductosPosicion').innerHTML = html;
    modalProductos.show();
}

function prepararNuevoRegistro() {
    document.getElementById('inventoryForm').reset();
    document.getElementById('editId').value = '';
    document.getElementById('modalRegistroLabel').innerHTML = `<i class="fa-solid fa-plus me-2"></i>Nuevo Movimiento`;
    document.getElementById('formFecha').value = new Date().toISOString().split('T')[0];
    actualizarCamposTraslado();
    modalRegistro.show();
}

function editarRegistro(id) {
    const item = service.movimientos.find(i => i.id == id);
    if (!item) return;
    if (item.trasladoId) {
        alert('Los movimientos de un traslado se gestionan como una operación completa. Elimine ambos registros y cree un nuevo traslado.');
        return;
    }

    document.getElementById('editId').value = item.id;
    document.getElementById('formFecha').value = item.fecha;
    document.getElementById('formMvto').value = item.mvto;
    document.getElementById('formPosicion').value = item.posicion;
    document.getElementById('formLote').value = item.lote;
    document.getElementById('formProducto').value = item.producto;
    document.getElementById('formPresentacion').value = item.presentacion;
    document.getElementById('formCantidad').value = item.cantidad;
    document.getElementById('formObservaciones').value = item.observaciones;
    actualizarCamposTraslado();

    document.getElementById('modalRegistroLabel').innerHTML = `<i class="fa-solid fa-pen-to-square me-2"></i>Editar Movimiento #${id}`;
    modalRegistro.show();
}

function actualizarCamposTraslado() {
    const esTraslado = document.getElementById('formMvto').value === 'Traslado';
    const destinoGroup = document.getElementById('destinoGroup');
    const destino = document.getElementById('formPosicionDestino');
    destinoGroup.classList.toggle('d-none', !esTraslado);
    destino.required = esTraslado;
    if (!esTraslado) destino.value = '';
}

async function guardarRegistro(e) {
    e.preventDefault();
    const datos = {
        id: document.getElementById('editId').value,
        fecha: document.getElementById('formFecha').value,
        mvto: document.getElementById('formMvto').value,
        posicion: document.getElementById('formPosicion').value,
        posicionDestino: document.getElementById('formPosicionDestino').value,
        lote: document.getElementById('formLote').value,
        producto: document.getElementById('formProducto').value,
        presentacion: document.getElementById('formPresentacion').value,
        cantidad: document.getElementById('formCantidad').value,
        observaciones: document.getElementById('formObservaciones').value
    };

    try {
        if (datos.mvto === 'Traslado') {
            if (datos.id) {
                throw new Error('Un traslado existente no se puede editar como un movimiento individual.');
            }
            await service.guardarTraslado(datos);
        } else {
            await service.guardarMovimiento(datos);
        }
        modalRegistro.hide();
        actualizarEstadoGeneral();
    } catch (err) {
        alert("Error al guardar: " + err.message);
    }
}

async function eliminarRegistro(id) {
    if (confirm(`¿Eliminar el registro #${id}?`)) {
        try {
            await service.eliminarRegistro(id);
            actualizarEstadoGeneral();
        } catch (err) {
            alert("Error al eliminar: " + err.message);
        }
    }
}

async function borrarTodo() {
    if (confirm("⚠️ ¿Estás seguro de ELIMINAR TODOS LOS REGISTROS?") && prompt("Escribe ELIMINAR para confirmar:") === 'ELIMINAR') {
        try {
            await service.borrarTodo();
            actualizarEstadoGeneral();
        } catch (err) {
            alert("Error al eliminar todo: " + err.message);
        }
    }
}

async function leerExcel(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async function(event) {
        const data = new Uint8Array(event.target.result);
        const workbook = XLSX.read(data, { type: 'array' });
        const sheet = workbook.Sheets[workbook.SheetNames[0]];
        const raw = XLSX.utils.sheet_to_json(sheet, { raw: false });

        const paraInsertar = raw.map(row => {
            let col = (row['Columna'] || '').toString().trim();
            let fila = (row['Fila'] || '').toString().trim();
            let pos = (col && fila && col !== '0' && fila !== '0') ? `${col}${fila}` : (row['posicion'] || row['Posición'] || 'Sin Ubicar');

            let prod = 'Otro';
            if (row['Aluminio'] === 'X') prod = 'Aluminio';
            else if (row['Magnesio'] === 'X') prod = 'Magnesio';
            else if (row['producto'] || row['Producto']) prod = row['producto'] || row['Producto'];

            let pres = 'Otra';
            if (row['125'] === 'X') pres = '125 kg';
            else if (row['200'] === 'X') pres = '200 kg';
            else if (row['presentacion'] || row['Presentación']) pres = row['presentacion'] || row['Presentación'];

            let fechaStr = row['Fecha'] || row['fecha'] || new Date().toISOString().split('T')[0];
            if (fechaStr.includes('/')) {
                const [dia, mes, anio] = fechaStr.split('/');
                fechaStr = `${anio}-${mes.padStart(2, '0')}-${dia.padStart(2, '0')}`;
            }

            return {
                fecha: fechaStr,
                mvto: row['Mvto'] || row['mvto'] || 'Ingreso',
                posicion: pos,
                producto: prod,
                presentacion: pres,
                lote: (row['Lote'] || row['lote'] || '-').toString().trim(),
                cantidad: parseInt(row['Cantidad'] || row['cantidad']) || 0,
                observaciones: (row['Observaciones'] || row['observaciones'] || '').toString().trim()
            };
        });

        try {
            const resultado = await service.importarDesdeExcel(paraInsertar);
            const detalleRechazados = resultado.rechazados ? ` Rechazados: ${resultado.rechazados}.` : '';
            alert(`¡Importados ${resultado.importados} registros exitosamente!${detalleRechazados}`);
            actualizarEstadoGeneral();
        } catch (err) {
            alert("Error al importar: " + err.message);
        }
    };
    reader.readAsArrayBuffer(file);
}

function exportarExcel() {
    const data = service.movimientos.map(i => ({
        "ID": i.id,
        "Fecha": i.FechaFormateada,
        "Movimiento": i.mvto,
        "Posición": i.posicion,
        "Producto": i.producto,
        "Presentación": i.presentacion,
        "Lote": i.lote,
        "Cantidad": i.cantidad,
        "Observaciones": i.observaciones
    }));

    const worksheet = XLSX.utils.json_to_sheet(data);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Inventario");
    XLSX.writeFile(workbook, `Inventario_Kemik_${new Date().toISOString().split('T')[0]}.xlsx`);
}

function exportarCSV() {
    let csv = "ID,Fecha,Movimiento,Posicion,Producto,Presentacion,Lote,Cantidad,Observaciones\n";
    service.movimientos.forEach(i => {
        csv += `"${i.id}","${i.FechaFormateada}","${i.mvto}","${i.posicion}","${i.producto}","${i.presentacion}","${i.lote}",${i.cantidad},"${i.observaciones}"\n`;
    });

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `inventario_kemik_${new Date().toISOString().split('T')[0]}.csv`;
    link.click();
}

function exportarBackupJSON() {
    const backup = {
        version: 1,
        exportadoEn: new Date().toISOString(),
        registros: service.movimientos.map(item => ({
            id: item.id,
            fecha: item.fecha,
            mvto: item.mvto,
            posicion: item.posicion,
            producto: item.producto,
            presentacion: item.presentacion,
            lote: item.lote,
            cantidad: item.cantidad,
            observaciones: item.observaciones,
            trasladoId: item.trasladoId,
            esTraslado: item.esTraslado
        }))
    };

    const blob = new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `inventario_kemik_backup_${new Date().toISOString().split('T')[0]}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 500);
}

async function importarBackupJSON(e) {
    const file = e.target.files[0];
    if (!file) return;

    try {
        const text = await file.text();
        const backup = JSON.parse(text);
        const registros = Array.isArray(backup?.registros) ? backup.registros : Array.isArray(backup) ? backup : null;

        if (!registros || registros.length === 0) {
            throw new Error('El archivo JSON no contiene registros válidos para restaurar.');
        }

        const confirmar = confirm(`Se reemplazarán los registros actuales por ${registros.length} del backup. ¿Deseas continuar?`);
        if (!confirmar) {
            e.target.value = '';
            return;
        }

        await service.restaurarDesdeJSON(registros);
        alert(`Backup restaurado correctamente: ${registros.length} registros importados.`);
        actualizarEstadoGeneral();
    } catch (err) {
        alert('Error al importar backup JSON: ' + err.message);
    } finally {
        e.target.value = '';
    }
}