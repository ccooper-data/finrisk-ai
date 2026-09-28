from __future__ import annotations
import hashlib,json,subprocess,tempfile
from pathlib import Path
import httpx
from finrisk.identity.sec_13f_pdf import parse_official_13f_pdf_text

SOURCES={
 "2009Q4":"https://www.sec.gov/divisions/investment/13f/13flist2009q4.pdf",
 "2010Q4":"https://www.sec.gov/divisions/investment/13f/13flist2010q4.pdf",
 "2011Q1":"https://www.sec.gov/divisions/investment/13f/13flist2011q1.pdf",
}
rows=[]
headers={"User-Agent":"finrisk-ai research contact"}
for vintage,url in SOURCES.items():
    r=httpx.get(url,headers=headers,timeout=120,follow_redirects=True);r.raise_for_status()
    with tempfile.TemporaryDirectory() as td:
        pdf=Path(td)/"x.pdf";txt=Path(td)/"x.txt";pdf.write_bytes(r.content)
        subprocess.run(["pdftotext","-layout",str(pdf),str(txt)],check=True)
        text=txt.read_text(errors="replace")
    d=parse_official_13f_pdf_text(text)
    rows.append({"vintage":vintage,"url":url,"sha256":hashlib.sha256(r.content).hexdigest(),
                 "bytes":len(r.content),"text_chars":len(text),"parsed_rows":len(d),
                 "unique_valid_cusips":int(d["cusip"].nunique()) if len(d) else 0,
                 "unique_issuer_names":int(d["issuer_name"].nunique()) if len(d) else 0})
out=Path("artifacts/identity/sec-13f-fidelity");out.mkdir(parents=True,exist_ok=True)
(out/"sec_13f_fidelity.json").write_text(json.dumps({"vintages":rows},indent=2,sort_keys=True))
print(json.dumps({"vintages":rows},indent=2))
