"""`recall` command: start the app on your own computer."""
from __future__ import annotations

import argparse
import os
import webbrowser
from threading import Timer

from . import __version__, create_app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="recall", description="Run the Recall flashcard app locally.")
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", 5000)))
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    p.add_argument("--version", action="version", version=f"recall {__version__}")
    args = p.parse_args(argv)

    app = create_app()
    url = f"http://127.0.0.1:{args.port}"
    print(f"Recall is running at {url}  (Ctrl+C to stop)")
    print(f"Your data is stored in {app.instance_path}")
    if not args.no_browser:
        Timer(1.0, webbrowser.open, [url]).start()
    # 127.0.0.1 = only reachable from this computer
    app.run(host="127.0.0.1", port=args.port, debug=os.getenv("FLASK_DEBUG") == "1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
