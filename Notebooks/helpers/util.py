import pathlib

def extract_asset_paths(subdir: pathlib.Path = pathlib.Path("."), regex: str = "*.*"):
    path_to_assets = pathlib.Path.home() / "Documents/Notebooks/assets" / subdir
    return list(path_to_assets.rglob(regex))