import http.server, socketserver, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
class Handler(http.server.SimpleHTTPRequestHandler):
    pass
with socketserver.ThreadingTCPServer(("127.0.0.1", 5180), Handler) as httpd:
    print("Serving on http://127.0.0.1:5180")
    httpd.serve_forever()
