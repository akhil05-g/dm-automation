import sys
import httpx

BASE_URL = "https://pseudogram-api.onrender.com"

def apply(name: str, email: str, phone: str, linkedin_url: str, whatsapp: str = None):
    payload = {
        "name": name,
        "email": email,
        "phone": phone,
        "whatsapp": whatsapp or phone,
        "linkedin_url": linkedin_url
    }
    print(f"Submitting application to {BASE_URL}/v1/apply ...")
    r = httpx.post(f"{BASE_URL}/v1/apply", json=payload)
    print(f"Status: {r.status_code}, Response: {r.text}")
    return r.status_code == 200

def keygen(email: str):
    print(f"Generating key for {email} via {BASE_URL}/v1/keygen ...")
    r = httpx.post(f"{BASE_URL}/v1/keygen", json={"email": email})
    print(f"Status: {r.status_code}, Response: {r.text}")
    if r.status_code == 200:
        data = r.json()
        print(f"\nSUCCESS! Your API Key is: {data.get('api_key')}")
        return data.get("api_key")
    return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python register.py keygen <email>")
        print("   OR: python register.py apply <name> <email> <phone> <linkedin_url> [whatsapp]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "keygen":
        keygen(sys.argv[2])
    elif cmd == "apply":
        name = sys.argv[2]
        email = sys.argv[3]
        phone = sys.argv[4]
        linkedin = sys.argv[5]
        whatsapp = sys.argv[6] if len(sys.argv) > 6 else phone
        if apply(name, email, phone, linkedin, whatsapp):
            keygen(email)
