import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

def extract_asset_paths(subdir: pathlib.Path = pathlib.Path("."), regex: str = "*.*"):
    path_to_assets = _REPO_ROOT / "Notebooks/assets" / subdir
    print(f"Searching in {path_to_assets}")
    return list(path_to_assets.rglob(regex))

def extract_cwd_files(regex: str = "*.*"):
    path_to_files = pathlib.Path.cwd()
    print(f"Searching in {path_to_files}")
    return list(path_to_files.rglob(regex))