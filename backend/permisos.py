PERMISOS = {
    "ver_inventario": "Consultar inventario, movimientos y posiciones",
    "gestionar_movimientos": "Registrar, editar y eliminar movimientos y traslados",
    "gestionar_lotes": "Cambiar estados de lotes y alertas de posiciones",
    "gestionar_catalogos": "Crear, editar y desactivar productos y presentaciones",
    "importar_excel": "Importar movimientos desde Excel",
    "restaurar_backup": "Restaurar copias de seguridad",
    "ver_auditoria": "Consultar el registro de auditoría",
    "gestionar_usuarios": "Crear usuarios, activarlos y restablecer contraseñas",
}

NOMBRES_ROLES = {
    "admin": "Administrador",
    "coordinador": "Coordinador logístico",
    "operador": "Operador",
    "consulta": "Consulta",
}

PERMISOS_POR_ROL = {
    "admin": frozenset((*PERMISOS, "borrar_todo")),
    "coordinador": frozenset(PERMISOS),
    "operador": frozenset({"ver_inventario", "gestionar_movimientos", "gestionar_lotes"}),
    "consulta": frozenset({"ver_inventario"}),
}

PERMISOS_QUE_REQUIEREN_INVENTARIO = frozenset({
    "gestionar_movimientos",
    "gestionar_lotes",
    "importar_excel",
    "restaurar_backup",
})
