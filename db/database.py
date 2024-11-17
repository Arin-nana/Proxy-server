import sqlite3
from config import DB_PATH

def init_db():
    conn = sqlite3.connect(DB_PATH)
    with open("db/schema.sql") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()

def save_request(client_ip, method, target_host, target_port, request_body):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO requests (client_ip, method, target_host, target_port, request_body)
                 VALUES (?, ?, ?, ?, ?)''', (client_ip, method, target_host, target_port, request_body))
    conn.commit()
    request_id = c.lastrowid
    conn.close()
    return request_id

def save_response(request_id, response_body):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO responses (request_id, response_body)
                 VALUES (?, ?)''', (request_id, response_body))
    conn.commit()
    conn.close()
