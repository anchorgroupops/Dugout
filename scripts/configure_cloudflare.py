import requests
import json
import sys

# Cloudflare Configuration
CLOUDFLARE_EMAIL = "anchorgroupops@gmail.com"
# The user provided this key in the latest message
CLOUDFLARE_API_KEY = "8c91653d2645cbd0cdca1c8cc318cb26dd82b"

BASE_URL = "https://api.cloudflare.com/client/v4"

headers = {
    "X-Auth-Email": CLOUDFLARE_EMAIL,
    "X-Auth-Key": CLOUDFLARE_API_KEY,
    "Content-Type": "application/json"
}

def get_account_id():
    response = requests.get(f"{BASE_URL}/accounts", headers=headers)
    data = response.json()
    if not data.get("success"):
        print(f"Error fetching accounts: {data}")
        sys.exit(1)
    # Usually there is only one account for personal users
    return data["result"][0]["id"]

def get_tunnels(account_id):
    response = requests.get(f"{BASE_URL}/accounts/{account_id}/cfd_tunnel", headers=headers)
    data = response.json()
    if not data.get("success"):
        print(f"Error fetching tunnels: {data}")
        sys.exit(1)
    return data["result"]

def update_tunnel_config(account_id, tunnel_id, new_hostname, service_url):
    # First, get the current configuration
    response = requests.get(f"{BASE_URL}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations", headers=headers)
    config_data = response.json()
    
    if not config_data.get("success"):
        print(f"Error fetching tunnel configuration: {config_data}")
        sys.exit(1)
    
    config = config_data.get("result", {}).get("config", {})
    ingress = config.get("ingress", [])
    
    print(f"Current Ingress Rules: {json.dumps(ingress, indent=2)}")
    
    # Cloudflare ingress rules must end with a catch-all (no hostname)
    # We insert our new rule before the catch-all
    
    new_rule = {
        "hostname": new_hostname,
        "service": service_url
    }
    
    # Check if the hostname already exists in ingress
    updated_ingress = []
    exists = False
    
    for rule in ingress:
        if rule.get("hostname") == new_hostname:
            print(f"Rule for {new_hostname} already exists. Updating...")
            updated_ingress.append(new_rule)
            exists = True
        else:
            updated_ingress.append(rule)
            
    if not exists:
        # Find the index of the catch-all rule (last one usually)
        if updated_ingress and "hostname" not in updated_ingress[-1]:
            catch_all = updated_ingress.pop()
            updated_ingress.append(new_rule)
            updated_ingress.append(catch_all)
        else:
            updated_ingress.append(new_rule)
            # Add a catch-all if missing (shouldn't happen with Remote Tunnels)
            updated_ingress.append({"service": "http_status:404"})
    
    # Update the configuration
    payload = {
        "config": {
            "ingress": updated_ingress
        }
    }
    
    print(f"Sending Update Payload: {json.dumps(payload, indent=2)}")
    
    update_response = requests.put(
        f"{BASE_URL}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations", 
        headers=headers, 
        json=payload
    )
    
    return update_response.json()

def get_zone_id(domain):
    response = requests.get(f"{BASE_URL}/zones?name={domain}", headers=headers)
    data = response.json()
    if not data.get("success") or not data.get("result"):
        print(f"Error fetching zone: {data}")
        sys.exit(1)
    return data["result"][0]["id"]

def ensure_dns_record(zone_id, tunnel_id, hostname):
    # Check if record exists
    response = requests.get(f"{BASE_URL}/zones/{zone_id}/dns_records?name={hostname}", headers=headers)
    data = response.json()
    if not data.get("success"):
        print(f"Error fetching DNS records: {data}")
        sys.exit(1)
    
    records = data.get("result", [])
    if records:
        print(f"DNS record for {hostname} already exists.")
        return
    
    # Create CNAME record pointing to <tunnel_id>.cfargotunnel.com
    tunnel_domain = f"{tunnel_id}.cfargotunnel.com"
    payload = {
        "type": "CNAME",
        "name": hostname,
        "content": tunnel_domain,
        "ttl": 1, # Auto
        "proxied": True
    }
    
    print(f"Creating DNS record: {hostname} -> {tunnel_domain}...")
    create_response = requests.post(f"{BASE_URL}/zones/{zone_id}/dns_records", headers=headers, json=payload)
    result = create_response.json()
    if result.get("success"):
        print(f"Successfully created DNS record for {hostname}")
    else:
        print(f"Failed to create DNS record: {result}")

if __name__ == "__main__":
    try:
        print("Fetching Account ID...")
        acc_id = get_account_id()
        print(f"Account ID: {acc_id}")
        
        domain = "joelycannoli.com"
        target_hostname = "sharks.joelycannoli.com"
        target_service = "http://192.168.7.222:3000"
        
        print(f"Fetching Zone ID for {domain}...")
        zone_id = get_zone_id(domain)
        print(f"Zone ID: {zone_id}")

        print("Fetching Tunnels...")
        tunnels = get_tunnels(acc_id)
        if not tunnels:
            print("No tunnels found.")
            sys.exit(0)
            
        print(f"Found {len(tunnels)} tunnel(s).")
        # Find the active tunnel.
        tunnel = tunnels[0]
        for t in tunnels:
            if t.get("name") == "n8n-rpi" or t.get("status") == "healthy":
                tunnel = t
                break
        
        tun_id = tunnel["id"]
        tun_name = tunnel["name"]
        print(f"Using Tunnel: {tun_name} ({tun_id})")
        
        print(f"Updating configuration for {target_hostname} -> {target_service}...")
        result = update_tunnel_config(acc_id, tun_id, target_hostname, target_service)
        
        if result.get("success"):
            print("Successfully updated Cloudflare Tunnel configuration!")
            
            print(f"Ensuring DNS record exists for {target_hostname}...")
            ensure_dns_record(zone_id, tun_id, target_hostname)
        else:
            print(f"Failed to update configuration: {result}")
            
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)
