import os
from google.oauth2 import service_account

SCOPES = [
    'https://www.googleapis.com/auth/cloud-platform',
]

def get_credentials():
    sa_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'service_account.json')
    if not os.path.exists(sa_path):
        raise FileNotFoundError(
            f"Service account JSON not found at '{sa_path}'. "
            "Place service_account.json in the project root or set "
            "GOOGLE_APPLICATION_CREDENTIALS in .env"
        )
    return service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
