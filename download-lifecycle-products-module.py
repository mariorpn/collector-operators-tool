import urllib.request
import json
import ssl
from datetime import datetime

def download_filtered_lifecycle_json():
    # URL da API completa
    url = "https://access.redhat.com/product-life-cycles/api/v1/products?all_versions=true"
    
    # Nome do arquivo para hoje: 2026-02-02
    hoje = datetime.now().strftime("%Y-%m-%d")
    filename = f"product_lifecycle_data_{hoje}.json"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }

    print(f"Buscando dados na Red Hat...")

    try:
        # Configuração para evitar erros de certificado SSL
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, context=context) as response:
            if response.status == 200:
                # 1. Lê os dados e decodifica para string
                raw_content = response.read().decode('utf-8')
                
                # 2. Converte a string em um dicionário Python
                full_json = json.loads(raw_content)
                
                # 3. Extrai apenas a lista que está dentro da chave "data"
                # Isso remove o {"data": ...} e inicia o arquivo com [{"uuid": ...
                just_data_list = full_json.get("data", [])
                
                # 4. Salva apenas a lista no arquivo
                with open(filename, 'w', encoding='utf-8') as f:
                    # indent=4 deixa o arquivo legível; se preferir uma linha só, remova.
                    json.dump(just_data_list, f, indent=4, ensure_ascii=False)
                
                print("-" * 30)
                print(f"✅ Processamento concluído!")
                print(f"Arquivo salvo: **{filename}**")
                print(f"O arquivo agora inicia diretamente com a lista de produtos.")
            else:
                print(f"❌ Erro HTTP: {response.status}")
    
    except Exception as e:
        print(f"❌ Erro ao processar: {e}")

if __name__ == "__main__":
    download_filtered_lifecycle_json()
