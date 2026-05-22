"""Phase 1: Probe workflow with several equipment items to discover output JSON structure."""
import requests
import json
import re
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "https://langtum.ship-cloud.cn"
API_KEY = "sk-1mwlg6bleo81"
WORKFLOW_ID = "cmpfa7efj525i7ao443aywzg6"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json; charset=utf-8",
}

# Pick diverse items: with manufacturer, without, different types
TEST_ITEMS = [
    {"manufacturer": "重庆齿轮箱有限责任公司", "model": "GWC70.82", "source_name": "1#主机减速齿轮箱"},
    {"manufacturer": "", "model": "", "source_name": "15PPM报警装置"},
    {"manufacturer": "浙江白云泵业有限公司", "model": "CLH150-315A", "source_name": "NO.1主海水泵"},
    {"manufacturer": "", "model": "", "source_name": "NO.1主机高温淡水泵"},
    {"manufacturer": "杭州兴龙泵业有限公司", "model": "X3G100×2", "source_name": "NO.1主机润滑油泵"},
]

def create_task(item):
    payload = {
        "workflowEntityId": WORKFLOW_ID,
        "input": {"equipment_list": [item]}
    }
    resp = requests.post(f"{BASE_URL}/api/v1/workflow/createTask", headers=HEADERS, json=payload)
    return resp.json()["data"]["taskId"]

def poll_task(task_id, max_wait=120):
    start = time.time()
    while time.time() - start < max_wait:
        resp = requests.get(f"{BASE_URL}/api/v1/workflow/queryTask/{task_id}",
                           headers={"Authorization": f"Bearer {API_KEY}"})
        data = resp.json()["data"]
        if data["status"] in ("SUCCEED", "FAILED"):
            return data
        time.sleep(5)
    return {"status": "TIMEOUT"}

print("=" * 60)
print("Phase 1: Probing workflow output format")
print("=" * 60)

for i, item in enumerate(TEST_ITEMS):
    print(f"\n--- Item {i+1}: {item['source_name']} ---")
    task_id = create_task(item)
    print(f"  taskId: {task_id}")

    result = poll_task(task_id)
    print(f"  status: {result['status']}")

    if result["status"] == "SUCCEED":
        output = result["detail"]["output"]
        print(f"  output keys: {list(output.keys())}")
        print(f"  full output:\n{json.dumps(output, ensure_ascii=False, indent=2)}")
    else:
        print(f"  FAILED: {json.dumps(result.get('detail', {}), ensure_ascii=False, indent=2)}")

print("\n" + "=" * 60)
print("Done. Check output above to confirm field mapping for Excel columns L-Y.")
