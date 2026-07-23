import os
from dotenv import load_dotenv

load_dotenv()

EMU_HOST = os.getenv("EMU_HOST")
EMU_PORT = os.getenv("EMU_PORT")
EMU_TENANT = os.getenv("EMU_TENANT")
EMU_USERNAME = os.getenv("EMU_USERNAME")
EMU_PASSWORD = os.getenv("EMU_PASSWORD")

EMU_BASE_URL = f"http://{EMU_HOST}:{EMU_PORT}"
