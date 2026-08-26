"""Punto de entrada unico: sin argumentos abre la ventana, con ellos hace de CLI.

Es la misma aplicacion. El paquete distribuido trae ademas un segundo
ejecutable sin consola para el acceso directo del escritorio, porque en Windows
un binario de consola abre una ventana negra detras de la interfaz.
"""
import sys


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) > 1:
        from .cli.main import main as cli
        return cli(argv[1:])
    from .gui.window import main as gui
    return gui([argv[0]])


if __name__ == "__main__":
    sys.exit(main())
