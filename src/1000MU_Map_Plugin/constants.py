import hashlib

INVALID_LAYER_NAMES = {'svg','g','path','rect','circle','ellipse','polygon','polyline','line','layer','group','root','vector'}

BUILTIN_HEIGHT_PRESETS = [
    ("路名_主路", 20.10),
    ("路名_支路", 15.10),
    ("商场边框", 60.0),
    ("商场", 80.0),
    ("深色box", 30.0),
    ("中色box", 40.0),
    ("浅色box", 50.0),
    ("主路", 20.0),
    ("支路", 15.0),
    ("绿化", 10.0),
    ("水", 5.0),
]

BUILTIN_PRESETS_HASH = hashlib.md5(str(BUILTIN_HEIGHT_PRESETS).encode()).hexdigest()

ADDON_MODULE = "1000MU_Map_Plugin"
