from config import TRAFFIC_LIMIT_MB

class UserTrafficLimit:
    def __init__(self, limit):
        self.limit = limit
        self.transferred = 0

    def add_data(self, data_size):
        self.transferred += data_size
        if self.transferred > self.limit:
            return True
        return False

traffic_limits = {}

def get_user_traffic_limit(client_ip):
    if client_ip not in traffic_limits:
        traffic_limits[client_ip] = UserTrafficLimit(TRAFFIC_LIMIT_MB * 1024 * 1024)
    return traffic_limits[client_ip]
