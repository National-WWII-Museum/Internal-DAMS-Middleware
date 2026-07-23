import requests

from . import config


def get_token(timeout=10):
    resp = requests.post(
        f"{config.EMU_BASE_URL}/{config.EMU_TENANT}/tokens",
        json={"username": config.EMU_USERNAME, "password": config.EMU_PASSWORD},
        headers={"Content-Type": "application/json", "Prefer": "representation=minimal"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.headers["Authorization"]


def get_auth_headers(timeout=10):
    return {"Authorization": get_token(timeout=timeout)}
