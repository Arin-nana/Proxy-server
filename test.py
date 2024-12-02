import pytest
import socket
import threading
import ssl
from unittest.mock import Mock, MagicMock
from main import (
    parse_host_header, forward_request_to_server, handle_client,
    proxy_server, handle_tunnel
)

# ----------------------------
# ТЕСТЫ ДЛЯ parse_host_header
# ----------------------------

def test_parse_host_header_with_port():
    """
    Тест на корректное извлечение хоста и порта из заголовка с портом.
    """
    request = b"GET / HTTP/1.1\r\nHost: example.com:8080\r\n\r\n"
    host, port = parse_host_header(request)
    assert host == "example.com"
    assert port == 8080


def test_parse_host_header_without_port():
    """
    Тест на корректное извлечение хоста и порта по умолчанию (порт 80 для HTTP).
    """
    request = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
    host, port = parse_host_header(request)
    assert host == "example.com"
    assert port == 80


def test_parse_host_header_missing_host():
    """
    Тест на случай отсутствия заголовка 'Host'. Ожидаем исключение ValueError.
    """
    request = b"GET / HTTP/1.1\r\n\r\n"
    with pytest.raises(ValueError, match="No Host header found in the request"):
        parse_host_header(request)


# -----------------------------------------
# ТЕСТЫ ДЛЯ forward_request_to_server
# -----------------------------------------

@pytest.mark.parametrize("is_https, expected_response", [
    (True, b"HTTPS/1.1 200 OK\r\n\r\n"),  # Тест для HTTPS запроса
    (False, b"HTTP/1.1 200 OK\r\n\r\n"),  # Тест для HTTP запроса
])
def test_forward_request_to_server(mocker, is_https, expected_response):
    """
    Тестирует отправку запроса к целевому серверу и получение корректного ответа.
    Проверяет работу как с HTTPS, так и с HTTP.
    """
    # Мокаем сокет с поддержкой контекстного менеджера
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recv.side_effect = [expected_response, b'']

    # Мокаем socket.create_connection и SSLContext.wrap_socket
    mocker.patch("socket.create_connection", return_value=mock_socket)
    mocker.patch("ssl.SSLContext.wrap_socket", return_value=mock_socket)

    # Выполняем запрос
    request = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
    response = forward_request_to_server("example.com", 443, request, is_https)

    # Проверяем, что SSL обертка использована для HTTPS
    if is_https:
        ssl.SSLContext.wrap_socket.assert_called_once_with(mock_socket, server_hostname="example.com")

    # Проверяем отправку запроса и корректность полученного ответа
    mock_socket.sendall.assert_called_once_with(request)
    assert response == expected_response


def test_forward_request_to_server_timeout(mocker):
    """
    Тест на обработку таймаута при получении ответа от сервера.
    Ожидаем, что функция вернет пустой байтовый объект.
    """
    # Мокаем сокет с поддержкой контекстного менеджера и таймаутом
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recv.side_effect = socket.timeout

    mocker.patch("socket.create_connection", return_value=mock_socket)

    request = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
    response = forward_request_to_server("example.com", 443, request, is_https=False)

    # Проверяем, что при таймауте возвращается пустой байтовый объект
    assert response == b""


# -----------------------------------------
# ТЕСТЫ ДЛЯ handle_client
# -----------------------------------------

def test_handle_client_http_request(mocker):
    """
    Тестирует обработку обычного HTTP запроса от клиента.
    """
    mock_socket = Mock()
    mocker.patch("main.forward_request_to_server", return_value=b"HTTP/1.1 200 OK\r\n\r\n")

    mock_socket.recv.return_value = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
    handle_client(mock_socket)

    # Проверяем, что клиент получил ответ от сервера
    mock_socket.sendall.assert_called_once_with(b"HTTP/1.1 200 OK\r\n\r\n")


def test_handle_client_connect_request(mocker):
    """
    Тестирует обработку CONNECT запроса для установления туннеля.
    """
    # Мокаем клиентский сокет
    mock_client_socket = Mock()
    mock_client_socket.recv.return_value = (
        b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n"
    )

    # Мокаем серверный сокет с поддержкой контекста
    mock_server_socket = MagicMock()
    mock_server_socket.__enter__.return_value = mock_server_socket
    mock_server_socket.recv.side_effect = [b"", b""]  # Имитируем закрытие соединения

    # Патчим socket.create_connection для возврата мокированного сокета
    mocker.patch("socket.create_connection", return_value=mock_server_socket)

    # Патчим forward_data, чтобы исключить долгую передачу данных
    mocker.patch("main.forward_data", autospec=True)

    # Выполняем функцию handle_client
    handle_client(mock_client_socket)

    # Проверяем, что клиенту было отправлено сообщение об установлении соединения
    mock_client_socket.sendall.assert_called_once_with(
        b"HTTP/1.1 200 Connection established\r\n\r\n"
    )

def test_handle_client_invalid_request(mocker):
    """
    Тестирует обработку пустого запроса от клиента. Ожидается, что соединение будет закрыто.
    """
    mock_socket = Mock()
    mock_socket.recv.return_value = b""  # Пустой запрос

    handle_client(mock_socket)

    # Проверяем, что сокет был закрыт
    mock_socket.close.assert_called_once()


# -----------------------------------------
# ТЕСТЫ ДЛЯ handle_tunnel
# -----------------------------------------

def test_handle_tunnel(mocker):
    """
    Тестирует установление туннеля и передачу данных через него.
    """
    mock_server_socket = MagicMock()
    mock_server_socket.__enter__.return_value = mock_server_socket
    mock_server_socket.recv.side_effect = [b"", b""]  # Имитируем закрытие туннеля

    mock_client_socket = Mock()
    mocker.patch("socket.create_connection", return_value=mock_server_socket)

    handle_tunnel(mock_client_socket, "example.com", 443)

    # Проверяем, что серверный сокет был вызван
    mock_server_socket.recv.assert_called()


# -----------------------------------------
# ТЕСТЫ ДЛЯ proxy_server
# -----------------------------------------

def test_proxy_server_socket(mocker):
    """
    Тестирует запуск прокси-сервера и обработку подключения клиента.
    """
    mock_server_socket = MagicMock()
    mock_server_socket.__enter__.return_value = mock_server_socket

    mock_client_socket = Mock()
    mock_server_socket.accept.return_value = (mock_client_socket, ('127.0.0.1', 12345))

    mocker.patch("socket.socket", return_value=mock_server_socket)

    stop_event = Mock()
    stop_event.is_set.side_effect = [False, True]  # Останавливаем сервер после одной итерации

    proxy_server('127.0.0.1', 8888, stop_event)

    # Проверяем, что сервер был привязан и слушает на порту
    mock_server_socket.bind.assert_called_once_with(('127.0.0.1', 8888))
    mock_server_socket.listen.assert_called_once_with(200)


def test_proxy_server_stop_on_exception(mocker):
    """
    Тестирует остановку прокси-сервера при возникновении KeyboardInterrupt.
    """
    mock_server_socket = MagicMock()
    mock_server_socket.__enter__.return_value = mock_server_socket
    mock_server_socket.accept.side_effect = KeyboardInterrupt

    mocker.patch("socket.socket", return_value=mock_server_socket)

    stop_event = threading.Event()
    proxy_server('127.0.0.1', 8888, stop_event)

    # Проверяем, что событие остановки было установлено
    assert stop_event.is_set()
