from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"


class OhsDistHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        clean_path = unquote(path.split("?", 1)[0].split("#", 1)[0])
        if clean_path == "/ohs":
            clean_path = "/ohs/"
        if clean_path.startswith("/ohs/"):
            clean_path = clean_path[len("/ohs") :]

        relative = clean_path.lstrip("/")
        if not relative:
            return str(DIST / "index.html")

        target = (DIST / relative).resolve()
        try:
            target.relative_to(DIST.resolve())
        except ValueError:
            return str(DIST / "index.html")

        if target.exists():
            return str(target)
        return str(DIST / "index.html")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 5173), OhsDistHandler)
    print("Serving OHS frontend at http://127.0.0.1:5173/ohs/")
    server.serve_forever()


if __name__ == "__main__":
    main()
