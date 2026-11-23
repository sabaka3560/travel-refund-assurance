"""Exercise live extraction only on marked specimen documents; save reproducible QA results."""
import json
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'deliverables' / 'demo-check'
OUT.mkdir(parents=True, exist_ok=True)
results = []
for filename in ['01_spicejet_DEL-BOM.pdf', '03_airindia_DEL-BOM_flex.pdf', '06_makemytrip_invoice_LUMPED_TAX.pdf', '08_indigo_BLR-HYD_photo.png']:
    started = time.monotonic()
    try:
        path = ROOT / 'demo_uploads' / filename
        mime = 'application/pdf' if path.suffix == '.pdf' else 'image/png'
        with path.open('rb') as f:
            r = httpx.post('http://127.0.0.1:8000/api/extract', files={'file': (filename, f, mime)}, timeout=90)
        data = r.json()
        result = {'file':filename, 'status':r.status_code, 'seconds':round(time.monotonic()-started,1)}
        if r.is_success:
            (OUT / (filename + '.extraction.json')).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            result.update(carrier=data.get('carrier'), fare_family=data.get('fare_family'), missing=data.get('missing'), taxes_only_lumped=data.get('taxes_only_lumped'))
        else:
            result['error'] = data.get('message', data.get('detail'))
        results.append(result)
        print(json.dumps(result, ensure_ascii=True), flush=True)
        if not r.is_success:
            break
    except Exception as e:
        results.append({'file':filename,'error':str(e),'seconds':round(time.monotonic()-started,1)})
        print(json.dumps(results[-1]), flush=True)
        break
(OUT / 'live-extraction-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
raise SystemExit(0 if len(results)==4 and all(r.get('status')==200 for r in results) else 1)
