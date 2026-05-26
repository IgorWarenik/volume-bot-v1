from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import logging

logger = logging.getLogger(__name__)

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
        
    def log_message(self, format, *args):
        # Отключаем спам в консоль от каждого пинга UptimeRobot
        pass
        
def run():
    try:
        server = HTTPServer(('0.0.0.0', 8080), RequestHandler)
        server.serve_forever()
    except Exception as e:
        logger.error(f"Ошибка запуска веб-сервера keep_alive: {e}")

def keep_alive():
    """Запускает мини-веб-сервер в отдельном потоке."""
    t = Thread(target=run)
    t.daemon = True
    t.start()
