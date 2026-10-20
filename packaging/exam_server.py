"""Start the existing exam application using only the bundled runtime."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import create_app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    app = create_app()

    @app.get('/_portable/health')
    def portable_health():
        return {'app': 'info-literacy-exam'}

    app.run(host='0.0.0.0', port=args.port, threaded=True, debug=False, use_reloader=False)
