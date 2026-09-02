import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_dir_defaut_egale_chemin_historique():
    import ads_fetch
    importlib.reload(ads_fetch)
    attendu = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(ads_fetch.__file__)), "..", "seo-audit")
    )
    assert ads_fetch.CONFIG_DIR == attendu
    assert ads_fetch.YAML_PATH == os.path.join(attendu, "google-ads.yaml")
    assert ads_fetch.SITES_JSON == os.path.join(attendu, "sites.json")


def test_config_dir_surcharge_env(monkeypatch):
    monkeypatch.setenv("REGIE_CONFIG_DIR", "/opt/regie-config")
    import ads_fetch
    importlib.reload(ads_fetch)
    assert ads_fetch.CONFIG_DIR == "/opt/regie-config"
    monkeypatch.delenv("REGIE_CONFIG_DIR")
    importlib.reload(ads_fetch)


def test_data_dir_surcharge_env(monkeypatch):
    monkeypatch.setenv("REGIE_DATA_DIR", "/opt/regie-data")
    import ads_fetch
    importlib.reload(ads_fetch)
    assert ads_fetch.DATA_DIR == "/opt/regie-data"
    monkeypatch.delenv("REGIE_DATA_DIR")
    importlib.reload(ads_fetch)


def test_ads_auth_meme_config_dir():
    import ads_auth
    import ads_fetch
    importlib.reload(ads_auth)
    importlib.reload(ads_fetch)
    assert os.path.dirname(ads_auth.DEFAULT_YAML_PATH) == ads_fetch.CONFIG_DIR
