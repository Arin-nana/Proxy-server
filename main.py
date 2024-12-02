import socket
import threading
import ssl
import logging
import certifi
import sqlite3

import time
MAX_RATE = 2**15  # Максимальная скорость в байтах в секунду


def log_request(client_ip, request_data):
    logging.info(f"Request from {client_ip}:\n{request_data.decode(errors='ignore')}")

def log_response(client_ip, response_data):
    logging.info(f"Response to {client_ip}:\n{response_data.decode(errors='ignore')}")


def rate_limited_forward_data(source, destination, max_rate):
    """
    Forward data from source to destination at a maximum rate (bytes per second).
    """
    interval = 0.1  # Интервал времени для проверки (в секундах)
    max_bytes_per_interval = max_rate * interval
    try:
        while True:
            start_time = time.time()
            data = source.recv(int(max_bytes_per_interval))
            if not data:
                break
            destination.sendall(data)
            elapsed_time = time.time() - start_time
            sleep_time = interval - elapsed_time
            if sleep_time > 0:
                time.sleep(sleep_time)
    except Exception as e:
        logging.error(f"Exception in rate_limited_forward_data: {e}")


DB_NAME = 'proxy_logs.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Создаем таблицу, если ее нет
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            client_ip TEXT,
            data_type TEXT,
            data TEXT
        )
    ''')
    # Получаем список существующих столбцов
    cursor.execute("PRAGMA table_info(logs)")
    columns = [column[1] for column in cursor.fetchall()]
    # Добавляем столбец 'data_type', если его нет
    if 'data_type' not in columns:
        cursor.execute("ALTER TABLE logs ADD COLUMN data_type TEXT")
    # Добавляем столбец 'data', если его нет
    if 'data' not in columns:
        cursor.execute("ALTER TABLE logs ADD COLUMN data TEXT")
    conn.commit()
    conn.close()

init_db()


def save_data_to_db(client_ip, data_type, data):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO logs (client_ip, data_type, data) VALUES (?, ?, ?)
    ''', (client_ip, data_type, data.decode('iso-8859-1', errors='ignore')))
    conn.commit()
    conn.close()



# ограничить количество трафика для уылауырута

def parse_host_header(request):
    headers = request.split(b'\r\n')
    host_header = next((header for header in headers if header.lower().startswith(b'host:')), None)
    if not host_header:
        raise ValueError("No Host header found in the request")

    target_host = host_header.split(b':', 1)[1].strip().decode()
    if ':' in target_host:
        target_host, target_port = target_host.split(':', 1)
        target_port = int(target_port)
    else:
        target_port = 443 if request.startswith(b'CONNECT') else 80
        logging.info(f"Detected {'HTTPS' if target_port == 443 else 'HTTP'}")
    return target_host, target_port


def rebuild_response_headers(status_line, headers):
    response_headers = status_line + b'\r\n'
    for key, value in headers.items():
        response_headers += f"{key}: {value}\r\n".encode('iso-8859-1')
    response_headers += b'\r\n'
    return response_headers


def forward_request_to_server(target_host, target_port, request, is_https):
    if is_https:
        context = ssl.create_default_context(cafile=certifi.where())
        context.minimum_version = ssl.TLSVersion.TLSv1_2

    logging.info(f"Connecting to {target_host}:{target_port}")
    try:
        with socket.create_connection((target_host, target_port), timeout=5) as proxy_socket:
            if is_https:
                proxy_socket = context.wrap_socket(proxy_socket, server_hostname=target_host)

            proxy_socket.sendall(request)

            # Чтение заголовков ответа
            response_headers = b""
            while True:
                chunk = proxy_socket.recv(1)
                if not chunk:
                    break
                response_headers += chunk
                if response_headers.endswith(b"\r\n\r\n"):
                    break

            if not response_headers:
                logging.error("No response from server")
                return b""

            logging.info(f"Received response headers:\n{response_headers.decode(errors='ignore')}")
        return response_headers

    except (socket.timeout, TimeoutError) as e:
        logging.error(f"Connection to {target_host}:{target_port} timed out: {e}")
        return b""
    except Exception as e:
        logging.error(f"Error during communication with {target_host}:{target_port}: {e}")
        return b""


def handle_client(client_socket, client_address):
    client_ip, client_port = client_address
    try:
        request = b''
        while True:
            data = client_socket.recv(8192)
            request += data
            if len(data) < 8192:
                break
        if not request:
            raise ValueError("Received empty request")

        logging.info(f"Received request from {client_ip}:\n{request.decode(errors='ignore')}")
        save_data_to_db(client_ip, 'request', request)
        log_request(client_ip, request)
        if request.startswith(b'CONNECT'):
            target_host, target_port = parse_host_header(request)
            client_socket.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            logging.info(f"Tunnel established to {target_host}:{target_port}")
            handle_tunnel(client_socket, target_host, target_port)
        else:
            target_host, target_port = parse_host_header(request)
            is_https = target_port == 443
            response = forward_request_to_server(target_host, target_port, request, is_https)
            logging.info(f"Sending response back to client. Length: {len(response)} bytes.")
            save_data_to_db(client_ip, 'response', response)
            client_socket.sendall(response)
            log_response(client_ip, response)
    except Exception as e:
        logging.error(f"Exception in handle_client: {e}")
    finally:
        client_socket.close()


def handle_tunnel(client_socket, target_host, target_port):
    try:
        with socket.create_connection((target_host, target_port)) as server_socket:
            threading.Thread(target=rate_limited_forward_data, args=(client_socket, server_socket, MAX_RATE)).start()
            rate_limited_forward_data(server_socket, client_socket, MAX_RATE)
    except Exception as e:
        logging.error(f"Exception in handle_tunnel: {e}")



def forward_data(source, destination):
    try:
        while True:
            data = source.recv(8192)
            if not data:
                break
            destination.sendall(data)
    except Exception as e:
        logging.error(f"Exception in forward_data: {e}")


def proxy_server(bind_host, bind_port, stop_event):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((bind_host, bind_port))
        server_socket.listen(200)
        server_socket.settimeout(1)
        logging.info(f"[*] Listening on {bind_host}:{bind_port}")

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
            logging.info("Stopping proxy server due to KeyboardInterrupt...")
            stop_event.set()
        finally:
            logging.info("Proxy server has been stopped.")



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    BIND_HOST = '127.0.0.1'
    BIND_PORT = 8888
    stop_event = threading.Event()

    proxy_server(BIND_HOST, BIND_PORT, stop_event)
