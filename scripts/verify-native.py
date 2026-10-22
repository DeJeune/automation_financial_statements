"""Developer-only migration oracle; Python is never bundled with the native app.
Run from the repository root: PYTHONPATH=. .venv/bin/python scripts/verify-native.py
Private attachments are intentionally excluded from the repository.
"""
import json, pathlib, subprocess, openpyxl, zipfile
from datetime import date, datetime
from src.config.shift_config import ShiftConfig
from src.processors.simple_report import SimpleReportProcessor
root=pathlib.Path.cwd(); base=root/'.context/attachments'
sources={'油品时间统计':base/'H08NC1/1(5).xlsx','加油明细':base/'cCDPeT/3(5).xlsx','充值明细':base/'mKlowY/4(5).xlsx'}
request={'sources':{k:str(v) for k,v in sources.items()},'day':20,'divisor':'3','count_divisor':'3','closing_balance':''}
req=root/'.context/native-request.json';req.write_text(json.dumps(request,ensure_ascii=False))
template=base/'0LPzc8/T-CD简20(1).xlsx';out=root/'.context/native-simple.xlsx'
r=subprocess.run(['cargo','run','--quiet','--manifest-path','native/Cargo.toml','-p','financial-engine','--','simple',str(req),str(template),str(out)],check=True,capture_output=True,text=True)
rust=json.loads(r.stdout); py=SimpleReportProcessor(ShiftConfig(date(2026,10,20),datetime(2026,10,20,6,58,4),datetime(2026,10,21,6,54,47),8.7)).build_updates(sources)
for sheet in py['updates']:
 for address,value in sheet['cells'].items():
  rv=rust['updates'][sheet['sheet']]['cells'][address]
  rv=None if rv['type']=='blank' else float(rv['value']) if rv['type']=='number' else '='+rv['value'] if rv['type']=='formula' else rv['value']
  assert rv==value,(address,rv,value)
print('Rust / Python: all generated values and formulas match')
before=openpyxl.load_workbook(template);after=openpyxl.load_workbook(out)
for s in before:
 assert str(s.merged_cells)==str(after[s.title].merged_cells)
 for row in s:
  for c in row:
   if c.coordinate not in rust['updates'].get(s.title,{}).get('cells',{}):assert c.value==after[s.title][c.coordinate].value,(s.title,c.coordinate)
print('Reopened output: unchanged cells and merged ranges preserved')
with zipfile.ZipFile(template) as a,zipfile.ZipFile(out) as b:
 assert a.namelist()==b.namelist()
 changed=[n for n in a.namelist() if a.read(n)!=b.read(n)]
 assert set(changed)<=set(['xl/styles.xml','xl/workbook.xml','xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml'])
 print('ZIP members changed:',changed)
print('D9',after['Sheet1']['D9'].value,'D13',after['Sheet1']['D13'].value)

# The supplied attachments do not include a legacy daily template. Build a small
# fixture with its existing pump sections and date rows to compare the mapping.
import asyncio
from src.processors.table_processor import TableProcessor
from src.processors.excel_updater import ExcelUpdater
from src.processors.source_tables import read_source
old_sources={'油品时间统计':base/'nTfMau/1(1).xlsx','油品优惠':base/'ZRUN60/2(1).xls','加油明细':base/'CnPUAE/3(1).xlsx','充值明细':base/'zc8gKB/4(1).xlsx'}
stats=read_source(old_sources['油品时间统计'],['机号','油品','加油升'])
legacy_template=root/'.context/native-daily-template.xlsx'
fixture=openpyxl.Workbook();sheet=fixture.active;sheet.title='调价前';row=3
for fuel,section in [('0#柴油','A'),('92#汽油','B'),('95#汽油','C')]:
 for machine in stats.loc[stats['油品']==fuel,'机号'].unique():
  sheet.cell(row,1,section);sheet.cell(row,2,str(int(machine))+'号');row+=1
sheet.cell(1, 10, "fixture extent")
fixture.create_sheet('调价后')
discounts=fixture.create_sheet('油品优惠明细 2')
discounts.cell(1, 52, 'fixture extent')
for d in range(1,32):discounts.cell(d+1,2,d)
fixture.save(legacy_template)
request['sources']={k:str(v) for k,v in old_sources.items()};request['day']=16
req.write_text(json.dumps(request,ensure_ascii=False))
legacy_output=root/'.context/native-daily.xlsx'
r=subprocess.run(['cargo','run','--quiet','--manifest-path','native/Cargo.toml','-p','financial-engine','--','daily',str(req),str(legacy_template),str(legacy_output)],check=True,capture_output=True,text=True)
rust=json.loads(r.stdout)
config=ShiftConfig(date(2026,10,16),datetime(2026,10,16,8,34,40),datetime(2026,10,17,8,32,40),8.7)
async def legacy():
 processor=TableProcessor(config);updates=[]
 for category,path in old_sources.items():updates.extend((await processor.process_table(path,category))['updates'])
 return updates
py_output=root/'.context/python-daily.xlsx';py_output.write_bytes(legacy_template.read_bytes());updater=ExcelUpdater(py_output);updater.apply_updates(asyncio.run(legacy()));updater.save_workbook();updater.close_workbook()
reference=openpyxl.load_workbook(py_output);actual=openpyxl.load_workbook(legacy_output)
for name,sheet in rust['updates'].items():
 for cell in sheet['cells']:
  assert actual[name][cell].value==reference[name][cell].value,(name,cell,actual[name][cell].value,reference[name][cell].value)
print('Legacy daily mappings: every generated cell matches the Python processor on the original four source files')
# Real workbook pictures must remain byte-identical through a cell edit.
for relative in ['a8JA1z/1(3).xlsx','But3s4/4(3).xlsx']:
 path=base/relative
 with zipfile.ZipFile(path) as z: assert any(n.startswith('xl/media/') for n in z.namelist()),path
print('Image-bearing attachment fixtures present for native workbook preservation tests')
