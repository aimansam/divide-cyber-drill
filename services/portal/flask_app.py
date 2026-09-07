"""
Flask portal - serves frontend and proxies API requests to FastAPI.

This is a reverse proxy that:
1. Serves the landing page at /
2. Serves the login page at /login
3. Serves the drill platform at /drill/*
4. Proxies /api/* requests to the FastAPI backend
5. Provides a single entry point (port 80) for everything
"""

import os
from flask import Flask, abort, send_from_directory, request, Response
import requests

app = Flask(__name__)

# Configuration
APP_DIR = os.path.join(os.path.dirname(__file__), 'app')
API_BACKEND = os.environ.get('API_BACKEND', 'http://api:8000')

# Timeout for API proxy requests (in seconds)
PROXY_TIMEOUT = 30


@app.route('/')
def landing():
    """Serve the landing page."""
    return send_from_directory(APP_DIR, 'landing.html')


@app.route('/login')
def login():
    """Serve the login page."""
    return send_from_directory(APP_DIR, 'login.html')


@app.route('/drill/')
def drill_index():
    """Serve the drill platform index."""
    return send_from_directory(APP_DIR, 'index.html')


def _is_asset_path(path):
    """True for file-like URLs that must 404 (not SPA-fallback to HTML)."""
    name = path.rsplit('/', 1)[-1]
    return '.' in name or path.startswith('assets/')


@app.route('/drill/<path:path>')
def drill_platform(path):
    """Serve drill platform files."""
    full = os.path.join(APP_DIR, path)
    if os.path.isfile(full):
        return send_from_directory(APP_DIR, path)
    if _is_asset_path(path):
        abort(404)
    return send_from_directory(APP_DIR, 'index.html')


@app.route('/api/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def proxy_api(path):
    """
    Proxy /api/* requests to the FastAPI backend.
    
    This forwards the request to the API backend and returns the response.
    All headers, query parameters, and request body are preserved.
    """
    # Build the backend URL (query params forwarded via params= below)
    backend_url = f"{API_BACKEND}/api/{path}"
    
    # Forward the request
    try:
        # Get the request data
        headers = {key: value for key, value in request.headers if key.lower() != 'host'}
        
        # Make the request to the backend
        resp = requests.request(
            method=request.method,
            url=backend_url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            params=request.args,
            allow_redirects=False,
            timeout=PROXY_TIMEOUT
        )
        
        # Build the response
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = [(name, value) for name, value in resp.raw.headers.items()
                           if name.lower() not in excluded_headers]
        
        response = Response(resp.content, resp.status_code, response_headers)
        return response
        
    except requests.exceptions.Timeout:
        return Response('{"error": "API request timeout"}', 504, mimetype='application/json')
    except requests.exceptions.ConnectionError:
        return Response('{"error": "API backend unavailable"}', 503, mimetype='application/json')
    except Exception as e:
        return Response(f'{{"error": "Proxy error: {str(e)}"}}', 500, mimetype='application/json')


@app.route('/healthz')
def health():
    """Health check endpoint."""
    return {'status': 'ok', 'service': 'portal'}


@app.route('/<path:path>')
def static_files(path):
    """Serve static files from the app directory."""
    full = os.path.join(APP_DIR, path)
    if os.path.isfile(full):
        return send_from_directory(APP_DIR, path)
    # Missing assets must 404 so the browser doesn't parse HTML as JS/CSS.
    if _is_asset_path(path):
        abort(404)
    # Extensionless routes fall back to the landing page (SPA routing).
    return send_from_directory(APP_DIR, 'landing.html')


if __name__ == '__main__':
    # Development mode
    app.run(host='0.0.0.0', port=80, debug=True)
