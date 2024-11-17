from network.request_parser import parse_host_header
from network.forwarder import forward_request_to_server
from handlers.traffic_limiter import get_user_traffic_limit
from db.database import save_request, save_response

def handle_client(client_socket, addr):
    try:
        request = b""
        while True:
            data = client_socket.recv(8192)
            if not data:
                break
            request += data

            user_limit = get_user_traffic_limit(addr[0])
            if user_limit.add_data(len(data)):
                client_socket.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return

        if not request:
            return

        target_host, target_port = parse_host_header(request)
        is_https = target_port == 443

        request_id = save_request(addr[0], "CONNECT" if is_https else "GET", target_host, target_port, request.decode(errors="ignore"))
        response = forward_request_to_server(target_host, target_port, request, is_https)
        save_response(request_id, response.decode(errors="ignore"))

        client_socket.sendall(response)
    finally:
        client_socket.close()
