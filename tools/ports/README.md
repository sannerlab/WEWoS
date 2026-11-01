# Port scripts

One-time scripts that generated `wewos/libs/volume.py` and `wewos/libs/imaging.py` from the
MGLTools Python 2 sources. They are kept as a record of what was changed. The generated
modules are now the sources: edit those, not the scripts.

```
# 1. convert the MGLTools module to Python 3 (code strings included)
python -c "from wewos.legacy.py2to3 import convert_module; ..."   # -> VolumeNodes_py3.py
# 2. patch it (Python 3.8+: the scripts use ast end line numbers)
python3 tools/ports/make_volume.py VolumeNodes_py3.py wewos/libs/volume.py tools/ports/volume_new_classes.py
python3 tools/ports/make_imaging.py PILNodes_py3.py wewos/libs/imaging.py tools/ports/imaging_new_classes.py
```

`*_new_classes.py` hold the nodes rewritten for the web page (and, after
`#--REGISTER--`, their registration in the library).
