import requests
from django.conf import settings

class BlynkAPIService:
    BASE_URL = "https://blynk.cloud/external/api"

    def __init__(self, token):
        self.token = token

    def _make_request(self, endpoint, params):
        url = f"{self.BASE_URL}/{endpoint}"
        params['token'] = self.token
        
        if settings.DEBUG:
            print(f"--- MOCK BLYNK API CALL ---")
            print(f"URL: {url}")
            print(f"Params: {params}")
            print(f"--------------------------")
            return True, "Mock command sent successfully."
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return True, response.json() if response.content else "Success"
        except requests.RequestException as e:
            return False, str(e)

    def set_virtual_pin(self, pin, value):
        return self._make_request('update', {f'v{pin}': value})

    def get_virtual_pin(self, pin):
        return self._make_request('get', {f'v{pin}': ''})