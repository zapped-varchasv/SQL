"""Generate a portable Power BI project from the audited CSV snapshot.

Only Python standard library required. Compressed embedded M tables deliberately
avoid machine-specific paths, credentials and mutable web refreshes. To update,
rerun pipeline.py then this script; open the PBIP and select Refresh.
"""
from pathlib import Path
import csv,json,zlib,base64,uuid
ROOT=Path(__file__).resolve().parents[1]
PBI=ROOT/'powerbi';REPORT=PBI/'AirlineReliability.Report';MODEL=PBI/'AirlineReliability.SemanticModel'
SCHEMA='https://developer.microsoft.com/json-schemas/fabric/item/report/definition/'
def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8',newline='\n')
def schema(part,version='1.0.0'):return SCHEMA+part+'/'+version+'/schema.json'
def literal(v):
    value="'"+v.replace("'","''")+"'" if isinstance(v,str) else str(v).lower() if isinstance(v,bool) else str(v)+'D'
    return {'expr':{'Literal':{'Value':value}}}
def field(table,column,measure=False):return {'Measure' if measure else 'Column':{'Expression':{'SourceRef':{'Entity':table}},'Property':column}}
def projection(table,column,measure=False):return {'field':field(table,column,measure),'queryRef':table+'.'+column,'nativeQueryRef':column}

tables=[]
mapping=[('Calendar','dim_date'),('Airlines','dim_airline'),('Routes','dim_route'),('Flights','fact_route_month'),('Network','network_month')]
for name,file in mapping:
    with (ROOT/f'data/processed/{file}.csv').open(encoding='utf-8',newline='') as f:
        reader=csv.reader(f);headers=next(reader);rows=list(reader)
    textcols={'airline','route','origin','destination','month_label','quarter'}
    columns=[];types=[]
    for h in headers:
        typ='dateTime' if h=='date' else 'string' if h in textcols else 'int64'
        col={'name':h,'dataType':typ,'sourceColumn':h,'summarizeBy':'none' if name!='Flights' and name!='Network' else 'sum'}
        if h=='date':col.update(formatString='dd MMM yyyy',summarizeBy='none')
        if h.endswith('_id'):col.update(isHidden=True,summarizeBy='none')
        columns.append(col);types.append('{"'+h+'", '+('type date' if h=='date' else 'type text' if h in textcols else 'Int64.Type')+'}')
    packed=base64.b64encode(zlib.compress(json.dumps(rows,separators=(',',':')).encode())[2:-4]).decode()
    expr=['let',f'    Rows = Json.Document(Binary.Decompress(Binary.FromText("{packed}", BinaryEncoding.Base64), Compression.Deflate)),',f'    Source = Table.FromRows(Rows, {json.dumps(headers).replace("[","{").replace("]","}")}),',f'    Typed = Table.TransformColumnTypes(Source, {{{", ".join(types)}}}, "en-AU")','in','    Typed']
    table={'name':name,'columns':columns,'partitions':[{'name':name,'mode':'import','source':{'type':'m','expression':expr}}]}
    if name=='Calendar':table['dataCategory']='Time';columns[0]['isKey']=True
    if name=='Network':table['description']='Entire reporting-airline network benchmark. Never add to Flights. July 2025 delayed counts contain a disclosed source exception.'
    tables.append(table)

measures=[
 ('Scheduled sectors','SUM(Flights[scheduled])','#,0','Volume'),
 ('Flown sectors','SUM(Flights[flown])','#,0','Volume'),
 ('Cancellations','SUM(Flights[cancelled])','#,0','Volume'),
 ('Delayed arrivals','SUM(Flights[arr_delayed])','#,0','Volume'),
 ('Cancellation rate','DIVIDE([Cancellations], [Scheduled sectors])','0.00%','Reliability'),
 ('Arrival OTP','DIVIDE(SUM(Flights[arr_on_time]), [Flown sectors])','0.00%','Reliability'),
 ('Departure OTP','DIVIDE(SUM(Flights[dep_on_time]), [Flown sectors])','0.00%','Reliability'),
 ('Arrival OTP prior year','CALCULATE([Arrival OTP], SAMEPERIODLASTYEAR(Calendar[date]))','0.00%','Time intelligence'),
 ('Arrival change pp','IF(NOT ISBLANK([Arrival OTP prior year]), 100 * ([Arrival OTP] - [Arrival OTP prior year]))','+0.00;-0.00;0.00','Time intelligence'),
 ('Cancellation rate 3M','VAR EndDate = MAX(Calendar[date]) RETURN CALCULATE([Cancellation rate], DATESINPERIOD(Calendar[date], EndDate, -3, MONTH))','0.00%','Time intelligence'),
 ('Route cancellation rank','IF([Scheduled sectors] > 0, RANKX(ALLSELECTED(Routes[route]), [Cancellations], , DESC, DENSE))','0','Prioritisation'),
 ('Top 10 cancellations','IF([Route cancellation rank] <= 10, [Cancellations])','#,0','Prioritisation'),
 ('Cancellation share','DIVIDE([Cancellations], CALCULATE([Cancellations], ALLSELECTED(Routes[route])))','0.0%','Prioritisation'),
 ('Months reported','DISTINCTCOUNT(Flights[date])','0','Coverage'),
 ('Coverage note','IF([Months reported] < 12, "Partial year or filtered period", IF([Scheduled sectors] < 1000, "Low volume: interpret cautiously", "12+ months; inspect route mix"))',None,'Coverage'),
 ('Network arrival OTP','DIVIDE(SUM(Network[arr_on_time]), SUM(Network[flown]))','0.00%','Network benchmark'),
 ('Network cancellation rate','DIVIDE(SUM(Network[cancelled]), SUM(Network[scheduled]))','0.00%','Network benchmark'),
]
flights=next(t for t in tables if t['name']=='Flights')
flights['measures']=[dict(name=n,expression=e,displayFolder=folder,**({'formatString':fmt} if fmt else {})) for n,e,fmt,folder in measures]
relationships=[{'name':str(uuid.uuid5(uuid.NAMESPACE_DNS,a+b+c)), 'fromTable':a,'fromColumn':b,'toTable':c,'toColumn':b,'crossFilteringBehavior':'oneDirection'} for a,b,c in [('Flights','date','Calendar'),('Flights','airline_id','Airlines'),('Flights','route_id','Routes'),('Network','date','Calendar')]]
write(MODEL/'definition.pbism',{'version':'1.0','settings':{}})
write(MODEL/'model.bim',{'name':'AirlineReliability','compatibilityLevel':1567,'model':{'culture':'en-AU','defaultPowerBIDataSourceVersion':'powerBI_V3','sourceQueryCulture':'en-AU','tables':tables,'relationships':relationships,'annotations':[{'name':'PBI_QueryOrder','value':json.dumps([x[0] for x in mapping])}]}})
write(PBI/'AirlineReliability.pbip',{'version':'1.0','artifacts':[{'report':{'path':'AirlineReliability.Report'}}],'settings':{'enableAutoRecovery':True}})
write(REPORT/'definition.pbir',{'$schema':'https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json','version':'4.0','datasetReference':{'byPath':{'path':'../AirlineReliability.SemanticModel'}}})
write(REPORT/'definition/version.json',{'$schema':schema('versionMetadata'),'version':'2.0.0'})
write(REPORT/'definition/report.json',{'$schema':schema('report'),'layoutOptimization':'None','themeCollection':{},'settings':{'useStylableVisualContainerHeader':True}})
write(REPORT/'definition/pages/pages.json',{'$schema':schema('pagesMetadata'),'pageOrder':['overview','routes'],'activePageName':'overview'})

def page(name,title):
    write(REPORT/f'definition/pages/{name}/page.json',{'$schema':schema('page'),'name':name,'displayName':title,'displayOption':'FitToPage','width':1280,'height':800,'objects':{'background':[{'properties':{'color':{'solid':{'color':literal('#EDF3F8')}},'transparency':literal(0)}}]}})
def visual(page,name,kind,x,y,w,h,title,roles=None,objects=None,sort=None):
    config={'visualType':kind,'visualContainerObjects':{'title':[{'properties':{'show':literal(True),'text':literal(title),'fontColor':{'solid':{'color':literal('#102A43')}},'fontSize':literal(13)}}],'background':[{'properties':{'show':literal(True),'color':{'solid':{'color':literal('#FFFFFF')}},'transparency':literal(0)}}]}}
    if roles:
        config['query']={'queryState':{role:{'projections':projs} for role,projs in roles.items()}}
        if sort: config['query']['sortDefinition']={'sort':[{'field':sort,'direction':'Descending'}]}
    if objects:config['objects']=objects
    write(REPORT/f'definition/pages/{page}/visuals/{name}/visual.json',{'$schema':schema('visualContainer','2.1.0'),'name':name,'position':{'x':x,'y':y,'z':0,'width':w,'height':h,'tabOrder':y+x},'visual':config})
def text(page,name,text,x,y,w,h,size=14):
    visual(page,name,'textbox',x,y,w,h,'',objects={'general':[{'properties':{'paragraphs':[{'textRuns':[{'value':text,'textStyle':{'fontFamily':'Segoe UI','fontSize':f'{size}pt','color':'#102A43'}}]}]}}]})
def slicer(page,name,table,col,x,y,w):visual(page,name,'slicer',x,y,w,90,col.replace('_',' ').title(),{'Values':[projection(table,col)]},objects={'data':[{'properties':{'mode':literal('Dropdown')}}]})
page('overview','01 | Operations overview');page('routes','02 | Route investigation')
text('overview','heading','AUSTRALIAN AIRLINE RELIABILITY',24,15,880,48,24)
text('overview','subtitle','BITRE reporting routes | 2023–2025 | Varchasv Gupta',24,64,920,34,12)
slicer('overview','year','Calendar','year',24,105,260);slicer('overview','airline','Airlines','airline',302,105,430);slicer('overview','origin','Routes','origin',750,105,506)
for i,metric in enumerate(['Scheduled sectors','Cancellations','Cancellation rate','Arrival OTP']):
    visual('overview','kpi'+str(i),'card',24+i*313,211,295,125,metric,{'Values':[projection('Flights',metric,True)]},objects={'labels':[{'properties':{'color':{'solid':{'color':literal('#007F82')}},'fontSize':literal(30)}}],'categoryLabels':[{'properties':{'show':literal(False)}}]})
visual('overview','trend','lineChart',24,354,610,344,'Monthly arrival and departure punctuality',{'Category':[projection('Calendar','month_label')],'Y':[projection('Flights','Arrival OTP',True),projection('Flights','Departure OTP',True)]})
visual('overview','routebar','clusteredBarChart',654,354,602,344,'Top 10 routes by cancellation volume',{'Category':[projection('Routes','route')],'Y':[projection('Flights','Top 10 cancellations',True)]},sort=field('Flights','Top 10 cancellations',True))
text('overview','scope','SELECTED ROUTES ONLY • OTP = on-time / flown; cancellations = cancelled / scheduled.\nClick a route to cross-filter. Volume identifies where to investigate; rates show relative frequency.\nPublic data contains no delay causes, passenger counts or measured business impact.',24,711,1232,72,11)
text('routes','heading','ROUTE INVESTIGATION',24,15,1000,48,24)
text('routes','subtitle','Use year and airline filters to explore volume, reliability and reporting coverage.',24,65,1220,38,12)
slicer('routes','year','Calendar','year',24,110,260);slicer('routes','airline','Airlines','airline',303,110,430);slicer('routes','route','Routes','route',752,110,504)
cols=[projection('Routes','route')]+[projection('Flights',m,True) for m in ['Scheduled sectors','Cancellations','Cancellation rate','Arrival OTP','Delayed arrivals','Months reported','Route cancellation rank']]
visual('routes','table','tableEx',24,222,1232,435,'Route-level evidence • sort any column',{'Values':cols},sort=field('Flights','Cancellations',True))
text('routes','note','INTERPRETATION\nCheck months reported and scheduled sectors before comparing rates. Airline comparisons reflect route mix.\nFull-year matched-route SQL analysis: 116 routes; 2025 arrival OTP improved by 2.61 pp versus 2024.\nSource: BITRE time series, downloaded 22 Sep 2026. Two network rows have disclosed count exceptions; route facts reconcile.',24,675,1232,108,12)
print('Generated portable PBIP:',PBI/'AirlineReliability.pbip')
