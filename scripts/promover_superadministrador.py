import argparse

from backend import create_app
from backend.service import ConflictoError


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promueve una cuenta existente a superadministrador.",
    )
    parser.add_argument("usuario", help="Nombre de usuario existente que se promoverá.")
    argumentos = parser.parse_args()

    app = create_app()
    usuarios = app.extensions["khemik"]["usuarios"]
    try:
        usuario = usuarios.promover_a_superadministrador(argumentos.usuario)
    except (ConflictoError, LookupError, ValueError) as error:
        parser.exit(1, f"No se pudo promover la cuenta: {error}\n")

    print(f"{usuario['username']} ahora es superadministrador.")


if __name__ == "__main__":
    main()
