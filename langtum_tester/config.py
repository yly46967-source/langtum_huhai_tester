"""Configuration constants for the Langtum workflow tester."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# Langtum API
LANGTUM_BASE_URL = "https://langtum.ship-cloud.cn"
LANGTUM_API_KEY = "sk-1mwlg6bleo81"
LANGTUM_WORKFLOW_ID = "cmpfa7efj525i7ao443aywzg6"

# Paths
EQUIPMENT_EXCEL = os.path.join(PROJECT_ROOT, "输出", "20艘船舶设备列表.xlsx")
DB_PATH = os.path.join(BASE_DIR, "langtum_tester.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
RESULT_DIR = os.path.join(BASE_DIR, "results")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

# Workflow polling
POLL_INTERVALS = [2, 4, 8, 10, 10] + [15] * 38  # max ~10 min per task

# Server
HOST = "0.0.0.0"
PORT = 8055
