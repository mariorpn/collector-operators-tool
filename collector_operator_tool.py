import json
import subprocess
import sys
import csv
import os
import urllib.request
import urllib.parse
import re
import base64
from datetime import datetime

# --- Constants and Cache ---
CACHE_SUBS = "cache_subs.json"
CACHE_CSVS = "cache_csvs.json"
CACHE_VERSION = "cache_version.json"
CACHE_LIFECYCLE = "cache_lifecycle.json"

# Red Hat Lifecycle Portal URLs
LIFECYCLE_PAGE_URL = "https://access.redhat.com/product-life-cycles"
LIFECYCLE_DIRECT_URL = "https://access.redhat.com/product-life-cycles/product_lifecycle_data.json"

def run_command(command):
    """Executes an oc command and returns the decoded JSON output."""
    print(f"Executing: {' '.join(command)} ...")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error executing command: {e}", file=sys.stderr)
        sys.exit(1)

def get_ocp_version(version_data):
    """Extracts the OCP cluster version from the clusterversion resource."""
    try:
        if version_data.get("status", {}).get("history", []):
            return version_data["status"]["history"][0]["version"]
        elif version_data.get("status", {}).get("desired", {}):
             return version_data["status"]["desired"]["version"]
    except Exception:
        pass
    return "N/A"

def get_data_with_cache(command, cache_file):
    """Returns data from cache if available, otherwise fetches it and updates cache."""
    if os.path.exists(cache_file):
        print(f"Using cache: {cache_file}")
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if content.strip():
                    return json.loads(content)
        except Exception as e:
            print(f"Error reading cache {cache_file}: {e}. Refetching...")

    data = run_command(command)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    return data

def ensure_lifecycle_data():
    """
    Checks for a local lifecycle file. 
    If not found, downloads the latest version from Red Hat.
    """
    pattern = re.compile(r"^product_lifecycle_data_.*.json$")
    local_files = [f for f in os.listdir('.') if pattern.match(f)]
    
    if local_files:
        local_files.sort(reverse=True)
        print(f"Lifecycle file found locally: {local_files[0]}")
        return local_files[0]

    print(f"No local lifecycle file found. Accessing Red Hat portal: {LIFECYCLE_PAGE_URL}")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    new_filename = f"product_lifecycle_data_{datetime.now().strftime('%Y-%m-%d')}.json"

    try:
        req = urllib.request.Request(LIFECYCLE_PAGE_URL, headers=headers)
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            
            # Look for the OUIA component button containing the JSON link
            tag_match = re.search(r'<a[^>]*data-ouia-component-id="OUIA-Generated-Button-link-4"[^>]*>', html)
            
            href_content = None
            if tag_match:
                tag_content = tag_match.group(0)
                href_match = re.search(r'href="([^"]+)"', tag_content)
                if href_match:
                    href_content = href_match.group(1)

            # If a Data URI is found in the href
            if href_content and ("data:text/json" in href_content or "data:application/json" in href_content):
                print("Lifecycle data found as Data URI. Decoding...")
                if "base64," in href_content:
                    _, b64_data = href_content.split("base64,", 1)
                    decoded_json = base64.b64decode(b64_data).decode('utf-8')
                else:
                    _, encoded_json = href_content.split(",", 1)
                    decoded_json = urllib.parse.unquote(encoded_json)
                
                with open(new_filename, 'w', encoding='utf-8') as f:
                    f.write(decoded_json)
                return new_filename

        # Fallback to direct URL if scraping fails
        print("Scraping failed or Data URI not found. Attempting direct download...")
        req_dl = urllib.request.Request(LIFECYCLE_DIRECT_URL, headers=headers)
        with urllib.request.urlopen(req_dl) as dl_response:
            content = dl_response.read()
            with open(new_filename, 'wb') as out_file:
                out_file.write(content)
            return new_filename

    except Exception as e:
        print(f"Critical error downloading lifecycle data: {e}", file=sys.stderr)
        sys.exit(1)

def get_lifecycle_data(file_path):
    """Loads the lifecycle JSON file."""
    print(f"Loading lifecycle data from: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def process_operators(subs_data, csvs_data, ocp_version):
    """Processes operator subscriptions and correlates them with ClusterServiceVersions."""
    operators_list = []
    csv_map = {}
    
    if csvs_data.get("items"):
        for csv_item in csvs_data["items"]:
            try:
                key = f"{csv_item['metadata']['namespace']}/{csv_item['metadata']['name']}"
                csv_map[key] = csv_item
            except KeyError: continue

    if not subs_data.get("items"):
        print("Warning: No Subscriptions found in cluster.")
        return []

    for sub in subs_data["items"]:
        spec = sub.get("spec", {})
        status = sub.get("status", {})
        metadata = sub.get("metadata", {})
        
        package_name = spec.get("name", "N/A")
        sub_source = spec.get("source", "")
        
        # Red Hat identification logic
        maintained_by_red_hat = (sub_source == "redhat-operators")

        installed_csv_name = status.get("installedCSV") or status.get("currentCSV")
        sub_namespace = metadata.get("namespace")
        
        csv_version = "N/A"
        display_name = package_name

        if installed_csv_name and sub_namespace:
            csv_key = f"{sub_namespace}/{installed_csv_name}"
            csv_data = csv_map.get(csv_key)

            if csv_data:
                csv_spec = csv_data.get("spec", {})
                csv_metadata = csv_data.get("metadata", {})
                csv_version = csv_spec.get("version", "N/A")
                display_name = csv_spec.get("displayName") or package_name
                
                if not maintained_by_red_hat:
                    provider_name = csv_spec.get("provider", {}).get("name", "").lower()
                    if "red hat" in provider_name:
                        maintained_by_red_hat = True
                    
                    provider_type = csv_metadata.get("labels", {}).get("operators.openshift.io/provider-type", "").lower()
                    if provider_type == "redhat":
                        maintained_by_red_hat = True

        operators_list.append({
            "name": package_name,
            "displayName": display_name,
            "version": csv_version,
            "channel": spec.get("channel", "N/A"),
            "maintainedByRedHat": maintained_by_red_hat,
            "ocpVersion": ocp_version
        })

    return operators_list

def build_lifecycle_map(lifecycle_data):
    """Maps products and lifecycle phases with robust EUS/ELS support."""
    l_map = {}
    
    # Target column names
    target_headers = {
        "maint": "Maintenance Support Ends",
        "els1": "Extended life cycle support (ELS) 1 ends",
        "els2": "Extended life cycle support (ELS) 2 ends",
        "els3": "Extended life cycle support (ELS) 3 ends",
        "elp": "Extended life phase ends"
    }

    for product in lifecycle_data:
        package = product.get("package")
        if not package: continue
        
        versions = {}
        for v in product.get("versions", []):
            v_name_raw = v.get("name", "")
            # Cleanup version names (e.g., "3.12 Maintenance" -> "3.12")
            v_name = v_name_raw.split(' ')[0].replace('.x', '').lstrip('v')
            
            phases = {}
            for p in v.get("phases", []):
                p_name_lower = p.get("name", "").lower()
                p_date = p.get("date", "N/A")
                
                if p_date and "T00" in str(p_date):
                    try:
                        dt = datetime.strptime(p_date.split('T')[0], "%Y-%m-%d")
                        p_date = dt.strftime("%B %d, %Y")
                    except: pass
                
                target = None
                
                # Maintenance mapping
                if "maintenance support" in p_name_lower:
                    target = target_headers["maint"]
                
                # ELS/EUS Terms logic
                elif any(x in p_name_lower for x in ["extended update support term 1", "els 1", "lifecycle support (els) 1"]):
                    target = target_headers["els1"]
                elif any(x in p_name_lower for x in ["extended update support term 2", "els 2", "lifecycle support (els) 2"]):
                    target = target_headers["els2"]
                elif any(x in p_name_lower for x in ["extended update support term 3", "els 3"]):
                    target = target_headers["els3"]
                elif "eus" in p_name_lower or "extended update support" in p_name_lower:
                    target = target_headers["els1"] # Fallback EUS to ELS 1
                
                elif "extended life phase" in p_name_lower or "elp" in p_name_lower:
                    target = target_headers["elp"]

                if target:
                    if target not in phases or phases[target] == "N/A":
                        phases[target] = p_date
            
            versions[v_name] = {
                "compatibility": v.get("openshift_compatibility", "N/A"),
                "phases": phases
            }
        l_map[package] = versions
    return l_map

def normalize_name(name):
    """Normalizes product names to improve lifecycle matching."""
    if not name: return ""
    n = name.lower()
    n = n.replace("operator", "").replace("red hat", "").replace("build of", "").replace("  ", " ").strip()
    return n

def combine_data(operators, lifecycle_map):
    """Combines cluster data with lifecycle data using fuzzy and normalized matching."""
    phase_headers = [
        "Maintenance Support Ends",
        "Extended life cycle support (ELS) 1 ends",
        "Extended life cycle support (ELS) 2 ends",
        "Extended life cycle support (ELS) 3 ends",
        "Extended life phase ends"
    ]
    headers = ["Operator Name", "Display Name", "Installed Version", "Channel", "Red Hat", "Third-Party", "OpenShift Compatibility"] + phase_headers
    
    normalized_lc_map = {normalize_name(k): v for k, v in lifecycle_map.items()}
    
    rows = []
    for op in operators:
        row = [
            op["name"], op["displayName"], op["version"], op["channel"],
            "Yes" if op["maintainedByRedHat"] else "No",
            "No" if op["maintainedByRedHat"] else "Yes"
        ]
        
        # Search lifecycle map
        p_data = lifecycle_map.get(op["displayName"]) or lifecycle_map.get(op["name"])
        
        # Fuzzy match if exact search fails
        if not p_data:
            norm_display = normalize_name(op["displayName"])
            norm_name = normalize_name(op["name"])
            p_data = normalized_lc_map.get(norm_display) or normalized_lc_map.get(norm_name)
            
            if not p_data:
                for lc_name, lc_data in lifecycle_map.items():
                    norm_lc = normalize_name(lc_name)
                    if norm_lc in norm_display or norm_lc in norm_name or norm_display in norm_lc:
                        p_data = lc_data
                        break

        v_data = None
        if p_data:
            # Cleanup version strings
            v_clean = re.split(r'[-+]', op["version"].lstrip('v'))[0]
            v_xy = ".".join(v_clean.split('.')[:2])
            v_x = v_clean.split('.')[0]
            
            # Cascading version search
            for key in [v_clean, v_xy, v_x]:
                if key in p_data:
                    v_data = p_data[key]
                    break
        
        if v_data:
            row.append(v_data["compatibility"])
            for ph in phase_headers:
                row.append(v_data["phases"].get(ph, "N/A"))
        else:
            row.extend(["N/A"] * (len(phase_headers) + 1))
        rows.append(row)
    
    return headers, rows

def save_html(headers, rows, filename="operator_report.html"):
    """Generates a dynamic and responsive HTML report."""
    print(f"Generating dynamic HTML report: {filename}")
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Operator Inventory</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background-color: #f8fafc; color: #1e293b; }}
        .main-wrapper {{ width: 100%; padding: 24px; }}
        .table-scroll {{ 
            overflow: auto; 
            max-height: calc(100vh - 160px); 
            border: 1px solid #e2e8f0;
            background: white;
            border-radius: 8px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        }}
        table {{ border-collapse: separate; border-spacing: 0; width: 100%; }}
        th {{ 
            position: sticky; top: 0; z-index: 20; 
            background: #f1f5f9; border-bottom: 2px solid #e2e8f0;
            white-space: nowrap; padding: 12px; font-size: 11px; font-weight: 700; color: #475569;
            text-transform: uppercase; letter-spacing: 0.05em;
        }}
        .sticky-col-1 {{ position: sticky; left: 0; z-index: 30; background: white; border-right: 1px solid #e2e8f0; }}
        .sticky-col-2 {{ position: sticky; left: 180px; z-index: 30; background: white; border-right: 1px solid #e2e8f0; }}
        th.sticky-col-1, th.sticky-col-2 {{ background: #f1f5f9; z-index: 40; }}
        
        tr:nth-child(even) td {{ background: #f8fafc; }}
        tr:nth-child(even) .sticky-col-1, tr:nth-child(even) .sticky-col-2 {{ background: #f8fafc; }}
        td {{ padding: 10px 12px; font-size: 13px; white-space: nowrap; border-bottom: 1px solid #f1f5f9; }}
        tr:hover td {{ background: #f1f5f9 !important; }}
        
        .badge-rh {{ background: #dcfce7; color: #166534; padding: 2px 10px; border-radius: 9999px; font-weight: 600; font-size: 11px; }}
        .badge-tp {{ background: #fee2e2; color: #991b1b; padding: 2px 10px; border-radius: 9999px; font-size: 11px; }}
        .text-na {{ color: #94a3b8; font-style: italic; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="main-wrapper">
        <div class="flex justify-between items-end mb-6">
            <div>
                <h1 class="text-3xl font-extrabold text-slate-900 tracking-tight">Operator Inventory</h1>
                <p class="text-slate-500 font-medium text-sm">Cluster data and Red Hat Lifecycle Support</p>
            </div>
            <div class="text-right">
                <p class="text-xs font-bold text-slate-400 uppercase tracking-widest">Generated: {date_now}</p>
            </div>
        </div>

        <div class="table-scroll">
            <table>
                <thead>
                    <tr>"""
    
    for i, h in enumerate(headers):
        cls = "sticky-col-1" if i == 0 else ("sticky-col-2" if i == 1 else "")
        html += f'<th class="{cls}">{h}</th>'
        
    html += "</tr></thead><tbody>"
    
    for row in rows:
        html += "<tr>"
        for i, cell in enumerate(row):
            cls = "sticky-col-1 font-semibold text-slate-700" if i == 0 else ("sticky-col-2 text-slate-500" if i == 1 else "")
            content = str(cell)
            if content == "Yes":
                content = f'<span class="{"badge-rh" if i==4 else "badge-tp"}">Yes</span>'
            elif content == "No":
                content = f'<span class="text-slate-400">No</span>'
            elif content == "N/A":
                content = '<span class="text-na">N/A</span>'
                
            html += f'<td class="{cls}">{content}</td>'
        html += "</tr>"
        
    html += "</tbody></table></div></div></body></html>"
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

def main():
    print("--- STARTING COLLECTION PROCESS ---")
    
    # Lifecycle data download
    lifecycle_file = ensure_lifecycle_data()
    
    # Cluster data fetching
    subs = get_data_with_cache(["oc", "get", "subs", "-A", "-o", "json"], CACHE_SUBS)
    csvs = get_data_with_cache(["oc", "get", "csv", "-A", "-o", "json"], CACHE_CSVS)
    version_raw = get_data_with_cache(["oc", "get", "clusterversion", "version", "-o", "json"], CACHE_VERSION)
    ocpv = get_ocp_version(version_raw)
    
    print(f"Cluster Version Detected: {ocpv}")
    
    lc_json = get_lifecycle_data(lifecycle_file)
    operators = process_operators(subs, csvs, ocpv)
    
    print(f"Total operators found: {len(operators)}")

    # OCP 4.14+ filter
    filtered = []
    for op in operators:
        v_str = op["ocpVersion"]
        if v_str == "N/A":
            filtered.append(op)
            continue
            
        try:
            parts = [int(s) for s in re.findall(r'\d+', v_str)]
            if len(parts) >= 2:
                major, minor = parts[0], parts[1]
                if (major == 4 and minor >= 14) or major > 4:
                    filtered.append(op)
            else:
                filtered.append(op)
        except: 
            filtered.append(op)

    print(f"Operators after filtering (OCP 4.14+): {len(filtered)}")

    if filtered:
        l_map = build_lifecycle_map(lc_json)
        h, r = combine_data(filtered, l_map)
        
        # Save CSV
        csv_file = "operator_inventory_report.csv"
        with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(h)
            writer.writerows(r)
        print(f"CSV report generated: {csv_file}")
            
        # Save HTML
        save_html(h, r)
        print("HTML report generated successfully!")
    else:
        print("NOTICE: No operators left after filter.")

if __name__ == "__main__":
    main()