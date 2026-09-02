#!/usr/bin/env python3
"""
Google Ads OAuth2 Setup — Adds the adwords scope and generates google-ads.yaml.

Usage:
  python3 ads_auth.py --credentials ~/gsc-credentials.json --developer-token XXXXXXXX

Steps before running:
  1. Google Ads > Admin (engrenage) > API Center → copier le Developer Token
  2. Verifier que le projet Google Cloud a l'API "Google Ads API" activee
     (console.cloud.google.com → APIs & Services → Enable APIs)
  3. Lancer ce script avec les credentials existants

Output:
  tools/seo-audit/ads-token.json  (OAuth2 refresh token)
  tools/seo-audit/google-ads.yaml (config pour le client Python)
  Resolution relative au script (dossier tools/seo-audit/ du depot), surchargeable
  par la variable d'environnement REGIE_CONFIG_DIR.
"""

import argparse
import json
import os
import yaml
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/adwords",
]

# Config partagee avec tools/seo-audit/ (source unique, pas de duplication
# de secrets) : le token et le yaml generes restent la-bas, meme si ce
# script est lance depuis tools/ads/.
# Resolution relative au script, surchargeable par REGIE_CONFIG_DIR (meme
# motif que ads_fetch.py, pour une installation exportee).
_ADS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get(
    "REGIE_CONFIG_DIR", os.path.abspath(os.path.join(_ADS_DIR, "..", "seo-audit"))
)
DEFAULT_TOKEN_PATH = os.path.join(CONFIG_DIR, "ads-token.json")
DEFAULT_YAML_PATH = os.path.join(CONFIG_DIR, "google-ads.yaml")


def authenticate(credentials_path: str, developer_token: str,
                 login_customer_id: str = None,
                 token_path: str = DEFAULT_TOKEN_PATH,
                 yaml_path: str = DEFAULT_YAML_PATH):

    # Charger le client_id et client_secret depuis le fichier credentials
    with open(credentials_path) as f:
        creds_data = json.load(f)
    installed = creds_data.get("installed") or creds_data.get("web", {})
    client_id = installed.get("client_id", "")
    client_secret = installed.get("client_secret", "")

    # OAuth2 flow avec le scope adwords
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    # Sauvegarder le token OAuth2
    with open(token_path, "w") as f:
        f.write(creds.to_json())
    print(f"Token OAuth2 sauvegarde : {token_path}")

    # Generer google-ads.yaml
    ads_config = {
        "developer_token": developer_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": creds.refresh_token,
        "use_proto_plus": True,
    }
    if login_customer_id:
        # Normaliser : supprimer tirets, garder chiffres uniquement
        ads_config["login_customer_id"] = login_customer_id.replace("-", "")

    with open(yaml_path, "w") as f:
        yaml.dump(ads_config, f, default_flow_style=False)
    print(f"Config Google Ads sauvegardee : {yaml_path}")
    print()
    print("Prochaine etape :")
    print("  python3 ads_fetch.py --site monsite")


def main():
    parser = argparse.ArgumentParser(description="Google Ads OAuth2 Setup")
    parser.add_argument("--credentials", required=True,
                        help="Chemin vers client_secret.json (meme fichier que pour GSC)")
    parser.add_argument("--developer-token", required=True,
                        help="Developer token depuis Google Ads > Admin > API Center")
    parser.add_argument("--token", default=DEFAULT_TOKEN_PATH,
                        help=f"Ou sauvegarder le token OAuth2 (defaut: {DEFAULT_TOKEN_PATH})")
    parser.add_argument("--yaml", default=DEFAULT_YAML_PATH,
                        help=f"Ou sauvegarder google-ads.yaml (defaut: {DEFAULT_YAML_PATH})")
    parser.add_argument("--login-customer-id",
                        help="ID du compte manager MCC (ex: 374-680-4450)")
    args = parser.parse_args()

    if not os.path.exists(args.credentials):
        print(f"Fichier credentials introuvable : {args.credentials}")
        return

    print("Lancement du flow OAuth2 (scope adwords inclus)...")
    print("Le navigateur va s'ouvrir pour reautoriser l'acces.\n")
    authenticate(args.credentials, args.developer_token,
                 args.login_customer_id, args.token, args.yaml)


if __name__ == "__main__":
    main()
