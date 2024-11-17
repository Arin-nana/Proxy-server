CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY,
    client_ip TEXT,
    method TEXT,
    target_host TEXT,
    target_port INTEGER,
    request_body TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY,
    request_id INTEGER,
    response_body TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(request_id) REFERENCES requests(id)
);
