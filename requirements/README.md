# Python dependencies

Run install commands from the repository root. These manifests target the
current Python 3.12 application environment, except `funasr.txt`, which is a
separate Python 3.9 environment.

File-only Bilibili and Weibo collection needs only `requests`; see the
[minimal collection workflow](../docs/01_赛季数据全流程.md#第一步采集原始资料).
The broader `collection.txt` group also supports browser cookie export and
explicit audio validation, so it retains Playwright, PyAV and the database driver.

| Manifest | Purpose | Install command |
| --- | --- | --- |
| `base.txt` | Shared database driver used by collection and web | `python -m pip install -r requirements/base.txt` |
| `collection.txt` | Official media and season collection tools, including PyAV and Playwright | `python -m pip install -r requirements/collection.txt` |
| `ocr.txt` | Optional S22/S23 visual-review OCR with OpenCV, RapidOCR, and ONNX Runtime | `python -m pip install -r requirements/ocr.txt` |
| `web.txt` | Website API runtime | `python -m pip install -r requirements/web.txt` |
| `test.txt` | Python 3.12 test environment for collection, web, audio utilities, and their tests | `python -m pip install -r requirements/test.txt` |
| `funasr.txt` | Paraformer production ASR and clip review in `.venv-funasr39` with Python 3.9 | `python -m pip install -r requirements/funasr.txt` |

`base.txt` is an include for the collection and web manifests; standalone
installation is only useful when a workflow needs the shared database driver.
`test.txt` includes both `collection.txt` and `web.txt`, then adds test and
audio-analysis packages.

`ocr.txt` includes `collection.txt`, so the visual-review scripts can use OCR
in the same Python 3.12 `.venv` as collection tools. Its OpenCV, RapidOCR,
ONNX Runtime, and NumPy pins match the versions already installed in that
environment. This optional group does not belong in the separate Python 3.9
FunASR environment.

Keep the FunASR environment separate from the Python 3.12 manifests. It pins
PyAV 15.1.0 and NumPy 1.26.4, while the collection and test environment uses
PyAV 16.1.0 and the test environment uses NumPy 2.5.4. Do not combine these
manifests into one environment.
