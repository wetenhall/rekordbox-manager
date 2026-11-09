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
        try:
            run(args.output_dir)
        except Exception:
            # Windowed Windows builds otherwise show a modal traceback dialog,
            # leaving CI waiting for a person instead of reporting the failure.
            import traceback
            args.output_dir.mkdir(parents=True, exist_ok=True)
            error = traceback.format_exc()
            (args.output_dir / 'selftest-error.txt').write_text(error, encoding='utf-8')
            if sys.stderr is not None:
                print(error, file=sys.stderr)
            raise SystemExit(1)
        return
    app = QApplication(sys.argv)
    app.setApplicationName("Rekordbox Manager")
    app.setOrganizationName("Rekordbox Manager")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "icon.png")))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
