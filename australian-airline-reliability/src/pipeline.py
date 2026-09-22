"""BITRE XLSX -> audited dimensional CSV -> SQLite -> SQL result marts.

Run: python src/pipeline.py --source data/raw/bitre_otp_snapshot_2026-09-22.xlsx
Or: python src/pipeline.py --from-curated (no download required).
"""
from pathlib import Path
import argparse, hashlib, json, sqlite3
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/processed'
COUNTS = ['scheduled','flown','cancelled','dep_on_time','arr_on_time','dep_delayed','arr_delayed']
TABLES = ['dim_date','dim_airline','dim_route','fact_route_month','network_month']
SOURCE_URL = 'https://www.bitre.gov.au/sites/default/files/documents/OTP_Time_Series_Master_Current_LATEST_0.xlsx'

def csv(df, name):
    df.to_csv(OUT / f'{name}.csv',index=False,lineterminator='\n',float_format='%.12g')

def curate(source):
    raw=pd.read_excel(source,sheet_name=0)
    d=raw.iloc[:,:12].copy()
    d.columns=['route','origin','destination','airline','date',*COUNTS]
    d=d[d.date.dt.year.between(2023,2025)].copy()
    assert d.date.nunique()==36, 'Incomplete 36-month cohort'
    assert not d.isna().any().any(), 'Missing required source values'
    normalized=int((d.airline=='virgin Australia').sum())
    d.airline=d.airline.replace({'virgin Australia':'Virgin Australia'})
    d.date=d.date.dt.strftime('%Y-%m-%d')
    assert not d.duplicated(['date','route','airline']).any(), 'Duplicate normalized grain'
    assert (d[COUNTS]>=0).all().all()
    assert (d.scheduled==d.flown+d.cancelled).all()
    d['scope']=d.apply(lambda r: 'industry' if r.route=='All Ports-All Ports' and r.airline=='All Airlines' else 'airline_network' if r.route=='All Ports-All Ports' else 'route_control' if r.airline=='All Airlines' else 'route_detail',axis=1)
    exceptions=[]
    for axis in ['dep','arr']:
        bad=d[d[f'{axis}_on_time']+d[f'{axis}_delayed']!=d.flown]
        for _,r in bad.iterrows():
            exceptions.append({'date':r.date,'route':r.route,'airline':r.airline,'scope':r.scope,'check':f'{axis}_partition','difference':int(r[f'{axis}_on_time']+r[f'{axis}_delayed']-r.flown),'treatment':'Preserved source; on-time rates use on-time/flown. Never use network delayed counts.'})
    detail=d[d.scope=='route_detail'].copy()
    controls=d[d.scope=='route_control'].set_index(['date','route'])[COUNTS].sort_index()
    grouped=detail.groupby(['date','route'])[COUNTS].sum().sort_index()
    pd.testing.assert_index_equal(grouped.index,controls.index)
    delta=grouped-controls
    for (date,route),row in delta.iterrows():
        for measure,value in row.items():
            if value:
                exceptions.append({'date':date,'route':route,'airline':'All Airlines','scope':'route_reconciliation','check':measure,'difference':int(value),'treatment':'Keep airline detail; discrepancy with published route total is disclosed.'})
    # Route facts must satisfy both count partitions. Network exceptions stay outside.
    for axis in ['dep','arr']:
        assert (detail[f'{axis}_on_time']+detail[f'{axis}_delayed']==detail.flown).all()
    airlines=pd.DataFrame({'airline':sorted(detail.airline.unique())})
    airlines.insert(0,'airline_id',range(1,len(airlines)+1))
    routes=detail[['route','origin','destination']].drop_duplicates().sort_values('route').reset_index(drop=True)
    assert routes.route.is_unique
    routes.insert(0,'route_id',range(1,len(routes)+1))
    dates=pd.DataFrame({'date':pd.date_range('2023-01-01','2025-12-31')})
    dates['year']=dates.date.dt.year; dates['month_number']=dates.date.dt.month
    dates['month_label']=dates.date.dt.strftime('%Y-%m');dates['quarter']='Q'+dates.date.dt.quarter.astype(str)
    dates.date=dates.date.dt.strftime('%Y-%m-%d')
    facts=detail.merge(airlines,on='airline',validate='many_to_one').merge(routes,on=['route','origin','destination'],validate='many_to_one')
    facts=facts[['date','airline_id','route_id',*COUNTS]].sort_values(['date','airline_id','route_id'])
    network=d[d.scope=='industry'][['date',*COUNTS]].sort_values('date')
    for name,df in zip(TABLES,[dates,airlines,routes,facts,network]):csv(df,name)
    csv(pd.DataFrame(exceptions,columns=['date','route','airline','scope','check','difference','treatment']),'quality_exceptions')
    manifest={'source':'BITRE Domestic airline on-time performance time series','source_url':SOURCE_URL,'downloaded':'2026-09-22','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_sheet':str(pd.ExcelFile(source).sheet_names[0]),'period':['2023-01','2025-12'],'source_cohort_rows':len(d),'route_fact_rows':len(facts),'routes':len(routes),'airlines':len(airlines),'case_normalized_rows':normalized,'scope_counts':d.scope.value_counts().to_dict(),'quality_exception_checks':len(exceptions),'route_reconciliation_checks':int(delta.size),'route_reconciliation_nonzero_checks':int((delta!=0).sum().sum()),'metrics':'OTP=SUM(on_time)/SUM(flown); cancellations=SUM(cancelled)/SUM(scheduled). Zero denominators return null.'}
    (OUT/'provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')

def build_database():
    db=ROOT/'reports/airline_reliability.sqlite'
    db.parent.mkdir(exist_ok=True)
    if db.exists(): db.unlink() # Only this generated database is replaced.
    con=sqlite3.connect(db)
    con.executescript((ROOT/'sql/01_schema.sql').read_text())
    for name in TABLES:
        frame=pd.read_csv(OUT/f'{name}.csv')
        rows=[tuple(r) for r in frame.itertuples(index=False,name=None)]
        con.executemany(f'INSERT INTO {name} VALUES ({",".join("?" for _ in frame.columns)})',rows)
    con.executescript((ROOT/'sql/02_analysis_views.sql').read_text())
    for view in ['annual','monthly','route_priority','matched_yoy','rolling','airline_year','network_annual']:
        csv(pd.read_sql_query(f'SELECT * FROM v_{view}',con),view)
    assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not con.execute('PRAGMA foreign_key_check').fetchall()
    assert con.execute('SELECT COUNT(*) FROM v_monthly').fetchone()[0]==36
    # Independently published rounded 2025 annual totals (BITRE, 6 March 2026).
    net=con.execute('SELECT arrival_otp,departure_otp,cancellation_rate FROM v_network_annual WHERE year=2025').fetchone()
    assert tuple(round(x*100,1) for x in net)==(76.9,77.7,2.5),net
    con.commit()
    print(pd.read_sql_query('SELECT * FROM v_annual',con).to_string(index=False))
    print(pd.read_sql_query('SELECT * FROM v_matched_yoy',con).to_string(index=False))
    print(pd.read_sql_query('SELECT route,scheduled,cancelled,cancellation_rate,arrival_otp,share_of_cancellations FROM v_route_priority WHERE year=2025 ORDER BY cancelled DESC LIMIT 5',con).to_string(index=False))
    con.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path);parser.add_argument('--from-curated',action='store_true')
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    if not args.from_curated:
        if not args.source:parser.error('--source or --from-curated is required')
        curate(args.source)
    build_database()
