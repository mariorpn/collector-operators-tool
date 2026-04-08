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

# --- Constantes de Cache ---
CACHE_SUBS = "cache_subs.json"
CACHE_CSVS = "cache_csvs.json"
CACHE_VERSION = "cache_version.json"
CACHE_LIFECYCLE = "cache_lifecycle.json"
# URL base e URL direta provável para o JSON
LIFECYCLE_PAGE_URL = "https://access.redhat.com/product-life-cycles?product=Red%20Hat%20OpenShift%20Data%20Foundation"
LIFECYCLE_DIRECT_URL = "https://access.redhat.com/product-life-cycles/product_lifecycle_data.json"

def run_command(command):
    """
    Executa um comando no shell e retorna a saída JSON decodificada.
    Encerra o script se o comando falhar ou a saída não for JSON.
    """
    print(f"Executando: {' '.join(command)} ...")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"Erro: A saída do comando não é um JSON válido.", file=sys.stderr)
            print(f"Erro JSON: {e}", file=sys.stderr)
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Erro: O comando 'oc' falhou (código de saída {e.returncode}).", file=sys.stderr)
        print(f"Stderr:\n{e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Erro: O comando 'oc' não foi encontrado no PATH.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Um erro inesperado ocorreu: {e}", file=sys.stderr)
        sys.exit(1)

def get_ocp_version(version_data):
    """Extrai a versão do cluster a partir dos dados do clusterversion."""
    try:
        if version_data.get("status", {}).get("history", []):
            return version_data["status"]["history"][0]["version"]
        elif version_data.get("status", {}).get("desired", {}):
             return version_data["status"]["desired"]["version"]
    except (KeyError, IndexError, TypeError):
        print(f"Aviso: Não foi possível determinar a versão do OCP.")
    return "N/A"

def get_data_with_cache(command, cache_file):
    """Carrega dados do cache se existir. Se não, consulta a API."""
    if os.path.exists(cache_file):
        print(f"Carregando dados do cache: {cache_file}")
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    print(f"Cache {cache_file} não encontrado. Consultando a API...")
    data = run_command(command)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    return data

def download_lifecycle_json():
    """
    Tenta encontrar os dados de lifecycle no portal da Red Hat através do componente OUIA
    ou via download direto.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    new_filename = f"product_lifecycle_data_{datetime.now().strftime('%Y-%m-%d')}.json"

    print(f"Buscando dados de ciclo de vida em: {LIFECYCLE_PAGE_URL}")
    try:
        req = urllib.request.Request(LIFECYCLE_PAGE_URL, headers=headers)
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            
            # Busca a tag <a> que contém o ID OUIA solicitado (independente da ordem dos atributos)
            tag_match = re.search(r'<a[^>]*data-ouia-component-id="OUIA-Generated-Button-link-4"[^>]*>', html)
            
            if tag_match:
                tag_content = tag_match.group(0)
                href_match = re.search(r'href="([^"]+)"', tag_content)
                
                if href_match:
                    href_content = href_match.group(1)
                    
                    # Verifica se é uma URI de dados (Data URI)
                    if "data:text/json" in href_content or "data:application/json" in href_content:
                        print("Dados encontrados diretamente no HTML (Data URI). Decodificando...")
                        
                        try:
                            if "base64," in href_content:
                                _, b64_data = href_content.split("base64,", 1)
                                decoded_json = base64.b64decode(b64_data).decode('utf-8')
                            elif "," in href_content:
                                _, encoded_json = href_content.split(",", 1)
                                decoded_json = urllib.parse.unquote(encoded_json)
                            else:
                                raise ValueError("Formato de URI de dados desconhecido.")

                            if decoded_json.strip():
                                with open(new_filename, 'w', encoding='utf-8') as f:
                                    f.write(decoded_json)
                                print(f"Dados salvos com sucesso: {new_filename}")
                                return new_filename
                            else:
                                print("Aviso: O conteúdo decodificado está vazio.")
                        except Exception as decode_err:
                            print(f"Erro ao decodificar Data URI: {decode_err}")

        # Se a lógica do OUIA falhar, tenta o download da URL direta
        print("Componente OUIA não encontrado ou inválido no HTML. Tentando URL direta padrão...")
        req_dl = urllib.request.Request(LIFECYCLE_DIRECT_URL, headers=headers)
        with urllib.request.urlopen(req_dl) as dl_response:
            content = dl_response.read()
            if content:
                with open(new_filename, 'wb') as out_file:
                    out_file.write(content)
                print(f"Download concluído via URL direta: {new_filename}")
                return new_filename
            else:
                raise ValueError("O download da URL direta retornou um arquivo vazio.")

    except Exception as e:
        print(f"Erro crítico ao obter dados de ciclo de vida: {e}", file=sys.stderr)
        sys.exit(1)

def find_local_lifecycle_file():
    """
    Procura arquivo local usando regex sem escape no ponto.
    """
    pattern = re.compile(r"^product_lifecycle_data_.*.json$")
    files = [f for f in os.listdir('.') if pattern.match(f)]
    if files:
        files.sort(reverse=True)
        return files[0]
    return None

def get_lifecycle_data():
    """Gerencia a obtenção dos dados: local ou download."""
    local_file = find_local_lifecycle_file()
    if local_file:
        print(f"Usando arquivo local: {local_file}")
        target_file = local_file
    else:
        target_file = download_lifecycle_json()

    try:
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content.strip():
                raise ValueError(f"O arquivo {target_file} está vazio.")
            return json.loads(content)
    except (IOError, json.JSONDecodeError, ValueError) as e:
        print(f"Erro ao processar o arquivo de ciclo de vida {target_file}: {e}", file=sys.stderr)
        # Se o arquivo local/baixado for inválido, podemos tentar baixar de novo se for o caso
        sys.exit(1)

def process_operators(subs_data, csvs_data, ocp_version):
    """Processa subscrições e correlaciona com ClusterServiceVersions."""
    operators_list = []
    csv_map = {}
    
    if csvs_data.get("items"):
        for csv_item in csvs_data["items"]:
            key = f"{csv_item['metadata']['namespace']}/{csv_item['metadata']['name']}"
            csv_map[key] = csv_item

    if not subs_data.get("items"):
        return []

    for sub in subs_data["items"]:
        try:
            spec = sub.get("spec", {})
            status = sub.get("status", {})
            metadata = sub.get("metadata", {})

            installed_csv = status.get("installedCSV")
            current_csv = status.get("currentCSV")
            csv_to_use = installed_csv or current_csv
            
            csv_version = "N/A"
            maintained_rh = False
            package_name = spec.get("name", "N/A")
            display_name = package_name

            if csv_to_use and metadata.get("namespace"):
                csv_key = f"{metadata['namespace']}/{csv_to_use}"
                csv_data = csv_map.get(csv_key)
                if csv_data:
                    csv_spec = csv_data.get("spec", {})
                    csv_version = csv_spec.get("version", "N/A")
                    display_name = csv_spec.get("displayName") or package_name
                    provider = csv_spec.get("provider", {}).get("name", "").lower()
                    maintained_rh = "red hat" in provider
                    
                    if not maintained_rh and csv_data["metadata"].get("labels"):
                        p_type = csv_data["metadata"]["labels"].get("operators.openshift.io/provider-type", "").lower()
                        maintained_rh = p_type == "redhat"

            operators_list.append({
                "name": package_name,
                "displayName": display_name,
                "version": csv_version,
                "channel": spec.get("channel", "N/A"),
                "maintainedByRedHat": maintained_rh,
                "ocpVersion": ocp_version
            })
        except Exception:
            continue
    return operators_list

def save_operators_csv(operators, csv_filename="operadores_openshift.csv"):
    """Filtra para 4.14+ e salva CSV básico."""
    filtered = []
    for op in operators:
        ocp_v = op.get("ocpVersion", "N/A")
        try:
            clean_v = ''.join(filter(lambda c: c.isdigit() or c == '.', ocp_v.lstrip('v')))
            parts = [int(p) for p in clean_v.split('.') if p.isdigit()]
            if parts and (parts[0] > 4 or (parts[0] == 4 and parts[1] >= 14)):
                filtered.append(op)
        except Exception:
            filtered.append(op)

    if not filtered: return []
    with open(csv_filename, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(["Nome do Operador", "Display Name", "Versão Instalada", "Canal", "Red Hat", "Third-Party"])
        for op in filtered:
            writer.writerow([op["name"], op["displayName"], op["version"], op["channel"], "Sim" if op["maintainedByRedHat"] else "Não", "Não" if op["maintainedByRedHat"] else "Sim"])
    return filtered

def build_lifecycle_map(lifecycle_data):
    """Mapeia versões e fases do produto."""
    l_map = {}
    phase_keys = {
        "maintenance support": "maintenance support ends",
        "els 1": "Extended life cycle support (ELS) 1 ends",
        "els 2": "Extended life cycle support (ELS) 2 ends",
        "extended life cycle": "Extended life cycle support (ELS) 1 ends",
        "extended life phase": "Extended life phase ends"
    }
    for product in lifecycle_data:
        package = product.get("package")
        if not package: continue
        versions = {}
        for v in product.get("versions", []):
            name = v.get("name", "")
            clean_name = name.split(' ')[0].replace('.x', '').lstrip('v')
            phases = {}
            for phase in v.get("phases", []):
                p_name = phase.get("name", "").lower()
                p_date = phase.get("date", "N/A")
                if "T00:00:00.000Z" in str(p_date):
                    p_date = datetime.strptime(p_date, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%B %d, %Y")
                for k_search, k_target in sorted(phase_keys.items(), key=lambda x: len(x[0]), reverse=True):
                    if k_search in p_name:
                        if k_target not in phases or phases[k_target] == "N/A":
                            phases[k_target] = p_date
                            break
            versions[clean_name] = {"compatibility": v.get("openshift_compatibility", "N/A"), "phases": phases}
        l_map[package] = versions
    return l_map

def combine_data(operators, l_map):
    """Combina dados de inventário com ciclo de vida."""
    phase_cols = ["maintenance support ends", "Extended life cycle support (ELS) 1 ends", "Extended life cycle support (ELS) 2 ends", "Extended life phase ends"]
    headers = ["Nome do Operador", "Display Name", "Versão Instalada", "Canal", "Red Hat", "Third-Party", "openshift compatibility"] + phase_cols
    rows = []
    for op in operators:
        row = [op["name"], op["displayName"], op["version"], op["channel"], "Sim" if op["maintainedByRedHat"] else "Não", "Não" if op["maintainedByRedHat"] else "Sim"]
        p_data = l_map.get(op["displayName"]) or l_map.get(op["name"])
        v_data = None
        if p_data:
            v_raw = op["version"].lstrip('v')
            v_xyz = v_raw.split('-')[0]
            v_xy = ".".join(v_xyz.split('.')[:2])
            v_x = v_xyz.split('.')[0]
            for vk in [v_raw, v_xyz, v_xy, v_x]:
                if vk in p_data:
                    v_data = p_data[vk]
                    break
        if v_data:
            row.append(v_data["compatibility"])
            for ph in phase_cols: row.append(v_data["phases"].get(ph, "N/A"))
        else:
            row.extend(["N/A"] * (len(phase_cols) + 1))
        rows.append(row)
    return headers, rows

def save_combined_csv(headers, rows, filename="operadores_com_lifecycle.csv"):
    with open(filename, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"Sucesso! CSV: {filename}")

def save_combined_html(headers, rows, filename="relatorio_operadores.html"):
    print(f"Gerando HTML: {filename}")
    html = f"""<!DOCTYPE html><html lang="pt-br"><head><meta charset="UTF-8"><title>Relatório Gerencial</title><script src="https://cdn.tailwindcss.com"></script>
    <style>body{{font-family:'Inter',sans-serif;}}.table-container{{overflow:auto;max-height:calc(100vh - 160px);background:white;}}
    table{{border-collapse:separate;border-spacing:0;width:100%;}}th{{position:sticky;top:0;z-index:20;background:#f3f4f6;padding:0.75rem 1rem;border-bottom:2px solid #e5e7eb;white-space:nowrap;}}
    .sticky-col-1{{position:sticky;left:0;z-index:30;background:white;border-right:2px solid #f3f4f6;}}.sticky-col-2{{position:sticky;left:160px;z-index:30;background:white;border-right:2px solid #f3f4f6;}}
    th.sticky-col-1,th.sticky-col-2{{background:#f3f4f6;z-index:40;}}td{{padding:0.75rem 1rem;border-bottom:1px solid #f3f4f6;white-space:nowrap;}}
    .status-pill{{padding:0.125rem 0.625rem;border-radius:9999px;font-size:0.75rem;font-weight:600;}}</style></head>
    <body class="bg-slate-50 p-6">
    <h1 class="text-2xl font-bold mb-4">Relatório de Operadores OpenShift</h1>
    <div class="table-container border rounded-lg shadow-lg"><table><thead><tr>"""
    for i, h in enumerate(headers):
        sc = "sticky-col-1" if i==0 else ("sticky-col-2" if i==1 else "")
        html += f"<th class='{sc}'>{h}</th>"
    html += "</tr></thead><tbody>"
    for r in rows:
        html += "<tr>"
        for i, c in enumerate(r):
            sc = "sticky-col-1 font-semibold" if i==0 else ("sticky-col-2" if i==1 else "")
            val = str(c)
            if val == "Sim":
                color = "bg-emerald-50 text-emerald-700" if headers[i]=="Red Hat" else "bg-orange-50 text-orange-700"
                content = f"<span class='status-pill {color}'>Sim</span>"
            elif val == "N/A": content = "<span class='text-gray-400 italic'>N/A</span>"
            else: content = val
            html += f"<td class='{sc}'>{content}</td>"
        html += "</tr>"
    html += "</tbody></table></div></body></html>"
    with open(filename, 'w', encoding='utf-8') as f: f.write(html)

def main():
    subs = get_data_with_cache(["oc", "get", "subscription.operators.coreos.com", "--all-namespaces", "-o", "json"], CACHE_SUBS)
    csvs = get_data_with_cache(["oc", "get", "clusterserviceversion.operators.coreos.com", "--all-namespaces", "-o", "json"], CACHE_CSVS)
    ocpv = get_ocp_version(get_data_with_cache(["oc", "get", "clusterversion", "version", "-o", "json"], CACHE_VERSION))
    lifecycle = get_lifecycle_data()
    ops = process_operators(subs, csvs, ocpv)
    if ops:
        filtered = save_operators_csv(ops)
        if filtered:
            h, r = combine_data(filtered, build_lifecycle_map(lifecycle))
            save_combined_csv(h, r)
            save_combined_html(h, r)

if __name__ == "__main__":
    main()

