# Repository detector demo

Download `original-repo-detector-python-demo-paged.zip` from this directory, extract it, and open PowerShell in the extracted folder. With Python 3.9 or later installed, run:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\original_repo_detector-1.0.0-py3-none-any.whl
.\.venv\Scripts\original-repo-detector.exe --help
```

Try the short assessment, then open its sources and limitations:

```powershell
.\.venv\Scripts\original-repo-detector.exe python-hyper/h11
.\.venv\Scripts\original-repo-detector.exe python-hyper/h11 --section sources
```

OpenClaw has enough saved measurements to demonstrate paging:

```powershell
.\.venv\Scripts\original-repo-detector.exe openclaw/openclaw --section activity --page 1
.\.venv\Scripts\original-repo-detector.exe openclaw/openclaw --section activity --page 2
```

Use `--json` for the complete structured record. The CLI fetches live GitHub metadata and displays packaged historical evidence. Setup may download certifi. This demo packages the evidence and CLI changes. The shared scoring model and website integration are separate work.
