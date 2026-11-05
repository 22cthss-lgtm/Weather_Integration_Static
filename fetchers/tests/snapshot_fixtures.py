"""Synthetic public contracts for history tests; never read live/public files."""
from datetime import datetime, timedelta
from pathlib import Path
import json

from src.publication import GROUPS
from src.rainfall_rankings import METRICS
from src.snapshots import IMAGE_TYPES, validate_resource

DAY = '2026-10-22'
FETCHED = '2026-10-22T00:05:00+00:00'
HISTORY_PATH = f'images/radar/history/{DAY}.json'
GAPS = ('pending', 'missing', 'failed', 'official_missing', 'legacy_unknown')


def image(kind, clock='00:20', *, stamp=None):
    if stamp is None:
        stamp = DAY if kind in ('sst','tchp') or kind.startswith('seaice_') else f'{DAY}T{clock}:00+08:00'
    return dict(image_type=kind,source='Fixture',title=f'Fixture {kind}',
                image_url=f'https://example.invalid/{kind}.png',source_url='https://example.invalid/',
                image_time=stamp,fetched_at=FETCHED)


def history(version, gap_field=None, *, kind='radar'):
    clocks = ['00:30'] if kind == 'rainfall' else ['00:00','00:10','00:20']
    items = [image(kind,c) for c in clocks if not (gap_field and c=='00:10')]
    data = dict(image_type=kind,date=DAY,timezone='Asia/Taipei',updated_at=FETCHED,
                range_start=f'{DAY}T{clocks[0]}:00+08:00',range_end=items[-1]['image_time'],
                expected_count=len(clocks),complete=gap_field is None,missing=[],failed=[],items=items)
    if version==2:data.update(schema_version=2,**{f:[] for f in GAPS})
    if gap_field:data[gap_field]=[f'{DAY}T00:10:00+08:00']
    return data


def write_seed(root, version, gap_field=None, *, reverse=False):
    """Build every required resource with fixed times and complete groups."""
    resources={}
    for kind in IMAGE_TYPES:
        if kind in GROUPS:
            children=[image(child) for child in GROUPS[kind]]
            data=dict(children[0],image_type=kind,images=children)
        else:data=image(kind,'00:30' if kind=='rainfall' else '00:20')
        resources[f'images/{kind}/latest.json']=data
    for kind in ('radar','satellite','rainfall'):
        resources[f'images/{kind}/history/{DAY}.json']=history(version,gap_field,kind=kind) if kind=='radar' else history(2,kind=kind)
    daily=[]
    for offset,label in enumerate(('今日','昨日','前日')):
        start=datetime.fromisoformat(f'{DAY}T00:00:00+08:00')-timedelta(days=offset)
        end=start+(timedelta(minutes=30) if offset==0 else timedelta(days=1))
        daily.append(dict(image('rainfall',stamp=end.isoformat()),label=label,
                          represented_date=start.date().isoformat(),accumulation_start=start.isoformat(),
                          accumulation_end=end.isoformat()))
    resources['images/rainfall/daily/latest.json']=dict(date=DAY,timezone='Asia/Taipei',fetched_at=FETCHED,items=daily)
    station=dict(rank=1,station_id='F1',station_name='Fixture',county='Fixture',town='Fixture',
                 rainfall=1,observed_at=f'{DAY}T00:00:00+00:00',fetched_at=FETCHED)
    resources['rainfall/rankings/latest.json']=dict(source='CWA',dataset_id='O-A0002-001',fetched_at=FETCHED,
        rankings={m:dict(metric=m,fetched_at=FETCHED,unit='mm',items=[dict(station)]) for m in METRICS})
    for name in sorted(resources,reverse=reverse):
        validate_resource(name,resources[name])
        path=Path(root)/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(resources[name],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return Path(root)/HISTORY_PATH
