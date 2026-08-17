import time
import httpx
import sys

from app.config import PSEUDOGRAM_API_KEY, PSEUDOGRAM_BASE_URL

def run_simulation(local_app_url: str, count: int = 500, duration_seconds: int = 10):
    webhook_url = f"{local_app_url.rstrip('/')}/webhook"
    print(f"Triggering simulation on {webhook_url} with {count} events over {duration_seconds}s...")
    
    headers = {"X-API-Key": PSEUDOGRAM_API_KEY}
    res = httpx.post(f"{PSEUDOGRAM_BASE_URL}/v1/simulate/start", json={
        "webhook_url": webhook_url,
        "count": count,
        "duration_seconds": duration_seconds
    }, headers=headers)
    
    print(f"Simulation trigger response: {res.status_code} {res.text}")
    if res.status_code != 200:
        print("Failed to start simulation.")
        return
        
    data = res.json()
    run_id = data.get("run_id")
    print(f"Simulation run_id: {run_id}")
    
    # Poll local stats every 5 seconds
    print("Monitoring local /stats vs remote truth...")
    for _ in range(60):
        time.sleep(5)
        try:
            stats_res = httpx.get(f"{local_app_url.rstrip('/')}/stats")
            print(f"[Local /stats] {stats_res.json()}")
        except Exception as e:
            print(f"Error fetching stats: {e}")
            
    # Fetch ground truth
    truth_res = httpx.get(f"{PSEUDOGRAM_BASE_URL}/v1/simulate/{run_id}/truth")
    print(f"\n[PseudoGram Ground Truth] {truth_res.status_code}")
    print(truth_res.text[:1000])

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_simulation.py <YOUR_WORKING_URL>")
        sys.exit(1)
    run_simulation(sys.argv[1])
