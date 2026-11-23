"""One-time Spotify login. Prints only the refresh token to stdout so it can be piped:

    python3 auth.py | gh secret set SPOTIFY_REFRESH_TOKEN
"""

import http.server
import os
import secrets
import sys
import urllib.parse
import webbrowser

import collect

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-recently-played"


def wait_for_callback() -> dict:
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Login finished. You can close this tab.".encode())

        def log_message(self, *args):
            pass

    with http.server.HTTPServer(("127.0.0.1", 8888), Handler) as server:
        while not result:
            server.handle_request()
    return result


def main() -> None:
    client_id, client_secret = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET first.")

    state = secrets.token_urlsafe(16)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
    })
    print(f"Opening the Spotify login page. If no browser opens, visit:\n{url}", file=sys.stderr)
    webbrowser.open(url)

    callback = wait_for_callback()
    if callback.get("state") != state:
        sys.exit("Login response state did not match; try again.")
    if "error" in callback:
        sys.exit(f"Spotify login failed: {callback['error']}")

    tokens = collect.token_request(
        {"grant_type": "authorization_code", "code": callback["code"], "redirect_uri": REDIRECT_URI},
        client_id,
        client_secret,
    )
    print(tokens["refresh_token"])
    print("Refresh token issued.", file=sys.stderr)


if __name__ == "__main__":
    main()
