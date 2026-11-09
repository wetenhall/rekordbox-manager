import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from .ui import MainWindow


def main():
    if '--self-test' in sys.argv:
        import argparse
        from .selftest import run
        parser = argparse.ArgumentParser()
        parser.add_argument('--self-test', action='store_true')
        parser.add_argument('--output-dir', type=Path, required=True)
        args = parser.parse_args()
        run(args.output_dir)
        return
    app = QApplication(sys.argv)
    app.setApplicationName("Rekordbox Manager")
    app.setOrganizationName("Rekordbox Manager")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "icon.png")))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
