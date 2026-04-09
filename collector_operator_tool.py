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

# --- Constantes e Cache ---
CACHE_SUBS = "cache_subs.json"
CACHE_CSVS = "cache_csvs.json"
CACHE_VERSION = "cache_version.json"
CACHE_LIFECYCLE = "cache_lifecycle.json"

# URLs do Portal de Lifecycle da Red Hat
LIFECYCLE_PAGE_URL = "https://access.redhat.com/product-life-cycles"
LIFECYCLE_DIRECT_URL = "https://access.redhat.com/product-life-cycles/product_lifecycle_data.json"

def run_command(command):
    """Executa um comando oc e retorna a saída JSON decodificada."""
    print(f"Executando: {' '.join(command)} ...")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Erro ao executar comando: {e}", file=sys.stderr)
        sys.exit(1)

def get_ocp_version(version_data):
    """Extrai a versão do cluster OCP do recurso clusterversion."""
    try:
        if version_data.get("status", {}).get("history", []):
            return version_data["status"]["history"][0]["version"]
        elif version_data.get("status", {}).get("desired", {}):
             return version_data["status"]["desired"]["version"]
    except Exception:
        pass
    return "N/A"

def get_data_with_cache(command, cache_file):
    """Retorna dados do cache se disponíveis, caso contrário busca e atualiza o cache."""
    if os.path.exists(cache_file):
        print(f"Usando cache: {cache_file}")
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if content.strip():
                    return json.loads(content)
        except Exception as e:
            print(f"Erro ao ler cache {cache_file}: {e}. Recoletando...")

    data = run_command(command)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    return data

def ensure_lifecycle_data():
    """
    Verifica se existe um arquivo de lifecycle local. 
    Caso contrário, baixa a versão mais recente da Red Hat.
    """
    pattern = re.compile(r"^product_lifecycle_data_.*.json$")
    local_files = [f for f in os.listdir('.') if pattern.match(f)]
    
    if local_files:
        local_files.sort(reverse=True)
        print(f"Arquivo de lifecycle encontrado localmente: {local_files[0]}")
        return local_files[0]

    print(f"Nenhum arquivo de lifecycle local encontrado. Acessando portal Red Hat: {LIFECYCLE_PAGE_URL}")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    new_filename = f"product_lifecycle_data_{datetime.now().strftime('%Y-%m-%d')}.json"

    try:
        req = urllib.request.Request(LIFECYCLE_PAGE_URL, headers=headers)
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            
            # Procura pelo componente OUIA que contém o link JSON
            tag_match = re.search(r'<a[^>]*data-ouia-component-id="OUIA-Generated-Button-link-4"[^>]*>', html)
            
            href_content = None
            if tag_match:
                tag_content = tag_match.group(0)
                href_match = re.search(r'href="([^"]+)"', tag_content)
                if href_match:
                    href_content = href_match.group(1)

            # Se encontrar um Data URI no href
            if href_content and ("data:text/json" in href_content or "data:application/json" in href_content):
                print("Dados de lifecycle encontrados como Data URI. Decodificando...")
                if "base64," in href_content:
                    _, b64_data = href_content.split("base64,", 1)
                    decoded_json = base64.b64decode(b64_data).decode('utf-8')
                else:
                    _, encoded_json = href_content.split(",", 1)
                    decoded_json = urllib.parse.unquote(encoded_json)
                
                with open(new_filename, 'w', encoding='utf-8') as f:
                    f.write(decoded_json)
                return new_filename

        # Fallback para URL direta se o scraper falhar
        print("Scraping falhou ou Data URI não encontrada. Tentando download direto...")
        req_dl = urllib.request.Request(LIFECYCLE_DIRECT_URL, headers=headers)
        with urllib.request.urlopen(req_dl) as dl_response:
            content = dl_response.read()
            with open(new_filename, 'wb') as out_file:
                out_file.write(content)
            return new_filename

    except Exception as e:
        print(f"Erro crítico ao baixar dados de lifecycle: {e}", file=sys.stderr)
        sys.exit(1)

def get_lifecycle_data(file_path):
    """Carrega o arquivo JSON de lifecycle."""
    print(f"Carregando dados de lifecycle de: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def process_operators(subs_data, csvs_data, ocp_version):
    """Processa as subscrições de operadores e as correlaciona com ClusterServiceVersions."""
    operators_list = []
    csv_map = {}
    
    if csvs_data.get("items"):
        for csv_item in csvs_data["items"]:
            try:
                key = f"{csv_item['metadata']['namespace']}/{csv_item['metadata']['name']}"
                csv_map[key] = csv_item
            except KeyError: continue

    if not subs_data.get("items"):
        print("Aviso: Nenhuma Subscription encontrada no cluster.")
        return []

    for sub in subs_data["items"]:
        spec = sub.get("spec", {})
        status = sub.get("status", {})
        metadata = sub.get("metadata", {})
        
        package_name = spec.get("name", "N/A")
        sub_source = spec.get("source", "")
        
        # Identificação Red Hat baseada na fonte da subscrição
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
    """Mapeia produtos e fases de lifecycle com suporte robusto a EUS/ELS."""
    l_map = {}
    
    # Mapeamento estendido para capturar variações do JSON
    # As chaves são termos de busca e os valores são os cabeçalhos finais
    standard_phases = {
        "full support": "full support ends",
        "maintenance support": "maintenance support ends",
        "extended life phase": "Extended life phase ends",
        "elp": "Extended life phase ends"
    }

    for product in lifecycle_data:
        package = product.get("package")
        if not package: continue
        
        versions = {}
        for v in product.get("versions", []):
            v_name_raw = v.get("name", "")
            # Limpeza de nomes de versão (ex: "3.12 Maintenance" -> "3.12")
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
                
                # Lógica para termos de ELS/EUS com suporte a termos (1, 2, 3)
                target = None
                
                # Busca por fases padrões
                for key, val in standard_phases.items():
                    if key in p_name_lower:
                        target = val
                        break
                
                # Se não for padrão, busca por ELS/EUS específicos
                if not target:
                    if any(x in p_name_lower for x in ["extended update support term 1", "els 1", "lifecycle support (els) 1"]):
                        target = "Extended life cycle support (ELS) 1 ends"
                    elif any(x in p_name_lower for x in ["extended update support term 2", "els 2", "lifecycle support (els) 2"]):
                        target = "Extended life cycle support (ELS) 2 ends"
                    elif any(x in p_name_lower for x in ["extended update support term 3", "els 3"]):
                        target = "Extended life cycle support (ELS) 3 ends"
                    elif "eus" in p_name_lower or "extended update support" in p_name_lower:
                        # Fallback para o primeiro termo se for genérico
                        target = "Extended life cycle support (ELS) 1 ends"

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
    """Normaliza nomes de produtos para melhorar a correspondência de lifecycle."""
    if not name: return ""
    n = name.lower()
    # Remove ruídos comuns
    n = n.replace("operator", "").replace("red hat", "").replace("build of", "").replace("  ", " ").strip()
    return n

def combine_data(operators, lifecycle_map):
    """Combina dados do cluster com dados de lifecycle usando busca fuzzy e normalizada."""
    phase_headers = [
        "maintenance support ends",
        "Extended life cycle support (ELS) 1 ends",
        "Extended life cycle support (ELS) 2 ends",
        "Extended life cycle support (ELS) 3 ends",
        "Extended life phase ends"
    ]
    headers = ["Nome do Operador", "Display Name", "Versão Instalada", "Canal", "Red Hat", "Third-Party", "OpenShift Compatibility"] + phase_headers
    
    normalized_lc_map = {normalize_name(k): v for k, v in lifecycle_map.items()}
    
    rows = []
    for op in operators:
        row = [
            op["name"], op["displayName"], op["version"], op["channel"],
            "Sim" if op["maintainedByRedHat"] else "Não",
            "Não" if op["maintainedByRedHat"] else "Sim"
        ]
        
        # Busca no mapa de lifecycle
        p_data = lifecycle_map.get(op["displayName"]) or lifecycle_map.get(op["name"])
        
        # Match fuzzy se o exato falhou
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
            # Limpeza de versão instalada (ex: 2.7.1-opr+ironic -> 2.7.1)
            v_clean = re.split(r'[-+]', op["version"].lstrip('v'))[0]
            v_xy = ".".join(v_clean.split('.')[:2])
            v_x = v_clean.split('.')[0]
            
            # Busca em cascata de versão
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

def save_html(headers, rows, filename="relatorio_operadores.html"):
    """Gera um relatório HTML dinâmico e responsivo."""
    print(f"Gerando relatório HTML dinâmico: {filename}")
    date_now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    html = f"""
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>Inventário de Operadores</title>
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
                <h1 class="text-3xl font-extrabold text-slate-900 tracking-tight">Inventário de Operadores</h1>
                <p class="text-slate-500 font-medium text-sm">Dados do cluster e Ciclos de Vida Red Hat</p>
            </div>
            <div class="text-right">
                <p class="text-xs font-bold text-slate-400 uppercase tracking-widest">Gerado em: {date_now}</p>
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
            if content == "Sim":
                content = f'<span class="{"badge-rh" if i==4 else "badge-tp"}">Sim</span>'
            elif content == "Não":
                content = f'<span class="text-slate-400">Não</span>'
            elif content == "N/A":
                content = '<span class="text-na">N/A</span>'
                
            html += f'<td class="{cls}">{content}</td>'
        html += "</tr>"
        
    html += "</tbody></table></div></div></body></html>"
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

def main():
    print("--- INICIANDO PROCESSO DE COLETA ---")
    
    # Automatiza o download dos dados de lifecycle
    lifecycle_file = ensure_lifecycle_data()
    
    # Busca dados do cluster usando cache
    subs = get_data_with_cache(["oc", "get", "subs", "-A", "-o", "json"], CACHE_SUBS)
    csvs = get_data_with_cache(["oc", "get", "csv", "-A", "-o", "json"], CACHE_CSVS)
    version_raw = get_data_with_cache(["oc", "get", "clusterversion", "version", "-o", "json"], CACHE_VERSION)
    ocpv = get_ocp_version(version_raw)
    
    print(f"Versão do Cluster Detectada: {ocpv}")
    
    lc_json = get_lifecycle_data(lifecycle_file)
    operators = process_operators(subs, csvs, ocpv)
    
    print(f"Total de operadores encontrados no cluster: {len(operators)}")

    # Filtro de Versão: OCP 4.14+
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

    print(f"Operadores filtrados (OCP 4.14+): {len(filtered)}")

    if filtered:
        l_map = build_lifecycle_map(lc_json)
        h, r = combine_data(filtered, l_map)
        
        # Salva CSV
        csv_file = "operadores_com_lifecycle.csv"
        with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(h)
            writer.writerows(r)
        print(f"Relatório CSV gerado: {csv_file}")
            
        # Salva HTML Dinâmico
        save_html(h, r)
        print("Relatório HTML gerado com sucesso!")
    else:
        print("AVISO: Nenhum operador restou após o filtro. Verifique sua versão do OCP.")

if __name__ == "__main__":
    main()