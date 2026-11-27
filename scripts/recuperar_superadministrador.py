import argparse
import os
from getpass import getpass

from backend import create_app
from backend.service import ConflictoError


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restablece el acceso de una cuenta superadministradora existente.",
    )
    parser.add_argument("usuario", help="Nombre de usuario existente, por ejemplo Gerente1.")
    argumentos = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = getpass("DATABASE_URL de Render (entrada oculta): ").strip()

    app = create_app({"SECRET_KEY": "maintenance-cli"})
    usuarios = app.extensions["khemik"]["usuarios"]
    try:
        usuarios.validar_recuperacion_superadministrador(argumentos.usuario)
    except (ConflictoError, LookupError, ValueError) as error:
        parser.exit(1, f"No se pudo restablecer el acceso: {error}\n")

    password = getpass("Nueva contraseña (no se mostrará): ")
    confirmacion = getpass("Confirma la nueva contraseña: ")
    if password != confirmacion:
        parser.exit(1, "Las contraseñas no coinciden.\n")

    try:
        usuario = usuarios.recuperar_superadministrador(argumentos.usuario, password)
    except (ConflictoError, LookupError, ValueError) as error:
        parser.exit(1, f"No se pudo restablecer el acceso: {error}\n")

    print(f"Acceso restablecido para {usuario['username']} ({usuario['role']}).")


if __name__ == "__main__":
    main()
