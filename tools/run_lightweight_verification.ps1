$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
& 'D:\WebLedgerHost\venv\Scripts\python.exe' 'C:\AX\cost\tools\verify_lightweight_runtime.py' *> 'C:\AX\cost\.local-archive\lightweight-20261003\runtime-verification.log'
exit $LASTEXITCODE
