from locust import HttpUser, task, between
import os

class WebsiteUser(HttpUser):
    host = "http://127.0.0.1:8000"
    wait_time = between(1, 2)

    def on_start(self):
        self.client.get("/")

    @task(1)
    def load_homepage(self):
        self.client.get("/")

    @task(2)
    def upload_file(self):
        file_path = os.path.join(os.path.dirname(__file__), 'test.csv')

        if os.path.exists(file_path):
            csrftoken = self.client.cookies.get('csrftoken')
            headers = {'X-CSRFToken': csrftoken} if csrftoken else {}

            with open(file_path, 'rb') as f:
                self.client.post("/", files={'file': f}, headers=headers)
        else:
            print(f"File not found: {file_path}")