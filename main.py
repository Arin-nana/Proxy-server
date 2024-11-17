import logging
import threading
import config
print(config.__file__)

from config import BIND_HOST, BIND_PORT
from db.database import init_db
from handlers.client_handler import handle_client
import socket

logging.basicConfig(level=logging.INFO, filename="logs/proxy.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s")

def proxy_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((BIND_HOST, BIND_PORT))
        server_socket.listen(200)
        server_socket.settimeout(1)
        logging.info(f"[*] Listening on {BIND_HOST}:{BIND_PORT}")
        stop_event = threading.Event()

        try:
            while not stop_event.is_set():
                try:
                    client_socket, addr = server_socket.accept()
                    logging.info(f"Accepted connection from {addr[0]}:{addr[1]}")
                    client_thread = threading.Thread(target=handle_client, args=(client_socket, addr))
                    client_thread.start()
                except socket.timeout:
                    continue
        except KeyboardInterrupt:
            logging.info("Stopping proxy server...")
        finally:
            logging.info("Proxy server stopped.")

if __name__ == "__main__":
    init_db()  # Инициализация базы данных
    proxy_server()
