"""Read-only monitoring inspection and explicit local configuration/recovery."""
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import quote

from .config import init_home, load_config, validate_monitoring
from .menu import choose
from .operator import _configuration
from .progress import read_runs, read_events


def _connection(home, write=False):
    path=Path(home)/'progress-deliveries.db'
    if not path.exists(): return None
    if path.is_symlink(): raise ValueError('unsafe progress delivery journal')
    return sqlite3.connect('file:'+quote(str(path),safe='/')+('?mode=rw' if write else '?mode=ro'),uri=True)


def deliveries(home):
    db=_connection(home)
    if db is None: return []
    try:
        rows=db.execute('SELECT run,channel,target,state,message FROM cards ORDER BY started DESC LIMIT 1000').fetchall()
        return [{'run_id':r[0],'channel':r[1],'destination':r[2],'state':r[3],
                 'message_id':json.loads(r[4]) if r[4] else None} for r in rows]
    except (sqlite3.Error,ValueError):
        raise ValueError('progress delivery journal unavailable') from None
    finally: db.close()


def status(home):
    settings=_configuration(Path(home))['monitoring']
    remote={}
    for channel,refs in [('discord',('discord_webhook_env',)),('whatsapp',('whatsapp_bridge_env','whatsapp_chat_env'))]:
        remote[channel]={'enabled':settings[channel], 'environment_ready':all(bool(os.environ.get(settings[k])) for k in refs)}
    recent=read_runs(home)
    return {'enabled':settings['enabled'],'bundled_skill':True,'terminal':settings['terminal'],
            'telegram':settings['telegram'],'heartbeat_seconds':settings['heartbeat_seconds'],
            'remote_destinations':remote,'runs_observed':len(recent),
            'visibility_failures':sum(bool(r.get('visibility_failed')) for r in recent),
            'delivery_attention':sum(d['state'] in ('creating','uncertain','edit_failed') for d in deliveries(home)),
            'network':'not contacted'}


def configure(home):
    init_home(home)
    config=load_config(home); settings=config['monitoring']
    options=[('enable','Enable task monitoring'),('disable','Disable task monitoring')]
    for channel in ('terminal','telegram','discord','whatsapp'):
        options.append((channel,('Disable ' if settings[channel] else 'Enable ')+channel+' progress'))
    options.append(('back','Back / cancel'))
    action=choose('Task monitoring',options)
    if action in (None,'back'): return {'changed':False}
    if action in ('enable','disable'): settings['enabled']=action=='enable'
    else: settings[action]=not settings[action]
    validate_monitoring(settings)
    path=Path(home)/'config.json'
    if path.is_symlink(): raise ValueError('configuration must not be a symlink')
    fd,temporary=tempfile.mkstemp(prefix='.monitor-config-',dir=home)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(config,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.chmod(temporary,0o600);os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    value=status(home);value['changed']=True
    value['note']='Restart Bishop or its gateway to apply settings. Remote destinations need their configured BISHOP environment variables.'
    return value


def resolve(home,args):
    if not re.fullmatch(r'[a-f0-9]{64}',args.destination): raise ValueError('use the destination hash from bishop monitor deliveries')
    db=_connection(home,write=True)
    if db is None: raise ValueError('progress delivery not found')
    try:
        key=(args.run,args.channel,args.destination)
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT state FROM cards WHERE run=? AND channel=? AND target=?',key).fetchone()
        if not row or row[0] not in ('creating','uncertain'): raise ValueError('progress delivery is not uncertain')
        if args.action=='retry':
            changed=db.execute("DELETE FROM cards WHERE run=? AND channel=? AND target=? AND state IN ('creating','uncertain')",key)
            note='Intent cleared. The next explicit run resume/event may send another card; a duplicate is possible.'
        else:
            message=args.message_id
            if not message or len(message)>256: raise ValueError('--message-id is required to adopt a sent card')
            if args.channel=='telegram':
                if not message.isdigit():raise ValueError('Telegram message ID must be numeric')
                message=int(message)
            changed=db.execute("UPDATE cards SET state='sent',message=? WHERE run=? AND channel=? AND target=? AND state IN ('creating','uncertain')",(json.dumps(message),*key))
            note='Known message adopted. Future progress edits will reuse it.'
        if changed.rowcount != 1:raise ValueError('progress delivery changed; inspect current status')
        db.commit();return {'resolved':True,'note':note}
    finally: db.close()


def execute(home,args):
    operation=args.monitor_command or 'status'
    try:
        if operation=='status':return status(home)
        if operation=='runs':return read_runs(home,args.limit)
        if operation=='events':return read_events(home,args.run,args.limit)
        if operation=='deliveries':return deliveries(home)
        if operation=='configure':return configure(home)
        return resolve(home,args)
    except sqlite3.Error:
        raise ValueError('monitoring journal unavailable') from None
