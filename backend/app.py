from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .service import InventarioService

ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, static_folder=None)
service = InventarioService()


def error_response(error: Exception, status: int = 400):
    return jsonify({"error": str(error)}), status


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "inventario-kemik"})


@app.get("/api/movimientos")
def movimientos():
    return jsonify([item.to_dict() for item in service.listar()])


@app.post("/api/movimientos")
def crear_movimiento():
    try:
        return jsonify(service.guardar_movimiento(request.get_json(force=True)).to_dict()), 201
    except ValueError as error:
        return error_response(error)


@app.put("/api/movimientos/<int:id_>")
def actualizar_movimiento(id_: int):
    try:
        data = request.get_json(force=True)
        data["id"] = id_
        return jsonify(service.guardar_movimiento(data))
    except ValueError as error:
        return error_response(error)


@app.post("/api/traslados")
def crear_traslado():
    try:
        return jsonify([item.to_dict() for item in service.guardar_traslado(request.get_json(force=True))]), 201
    except ValueError as error:
        return error_response(error)


@app.delete("/api/movimientos/<int:id_>")
def eliminar_movimiento(id_: int):
    service.eliminar(id_)
    return jsonify({"ok": True})


@app.delete("/api/movimientos")
def borrar_movimientos():
    service.borrar_todo()
    return jsonify({"ok": True})


@app.get("/api/stock")
def stock():
    return jsonify(service.stock())


@app.get("/api/estadisticas")
def estadisticas():
    return jsonify(service.estadisticas())


@app.get("/api/posiciones")
def posiciones():
    return jsonify(service.mapa_posiciones())


@app.post("/api/importar")
def importar():
    try:
        return jsonify(service.importar(request.get_json(force=True).get("registros", [])))
    except ValueError as error:
        return error_response(error)


@app.post("/api/restaurar")
def restaurar():
    try:
        payload = request.get_json(force=True)
        registros = payload if isinstance(payload, list) else payload.get("registros", [])
        service.restaurar(registros)
        return jsonify({"ok": True, "importados": len(registros)})
    except (ValueError, TypeError, KeyError) as error:
        return error_response(error)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def frontend(path: str):
    view_dir = ROOT / "vista y stilo"
    if path:
        candidates = [ROOT / path, view_dir / path]
        for candidate in candidates:
            if candidate.is_file():
                return send_from_directory(str(candidate.parent), candidate.name)
        if "." in Path(path).name:
            return error_response(ValueError(f"No se encontró el archivo solicitado: {path}"), 404)
    return send_from_directory(str(view_dir), "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
