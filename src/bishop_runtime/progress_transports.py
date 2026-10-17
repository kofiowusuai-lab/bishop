"""Bounded lifecycle-only progress delivery; remote destinations are opt-in."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_PHASES={'started':'Starting','resumed':'Resuming','interrupted':'Interrupted','run_started':'Starting','model_started':'Waiting for model','tool_started':'Running tool','tool_completed':'Tool finished','awaiting_approval':'Awaiting approval','needs_reconciliation':'Needs reconciliation','run_completed':'Completed','completed':'Completed','failed':'Failed','run_failed':'Failed','heartbeat':'Working','step_limit':'Step limit reached'}
_STATUSES={'interrupted','running','completed','failed','awaiting_approval','needs_reconciliation','step_limit'}

def render_progress(snapshot):
    """Do not render arbitrary model data, errors, arguments or output."""
    run=str(snapshot.get('run_id',''))
    run=run[:12] if re.fullmatch(r'[A-Za-z0-9_-]{1,128}',run) else 'unknown'
    phase=_PHASES.get(snapshot.get('phase'),'Working')
    status=snapshot.get('status'); status=status if status in _STATUSES else 'running'
    elapsed=snapshot.get('elapsed',0)
    elapsed=int(elapsed) if isinstance(elapsed,(int,float)) and math.isfinite(elapsed) else 0
    step=snapshot.get('step',0); step=step if type(step) is int else 0
    tool=snapshot.get('tool'); tool=' · '+tool if isinstance(tool,str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}',tool) else ''
    return f'Bishop · {run}\n{phase}{tool}\n{status} · step {max(0,min(step,100000))} · {max(0,min(elapsed,31536000))}s elapsed'

class TerminalProgress:
    def __init__(self,output): self.output=output; self.last=None; self.open_line=False
    def __call__(self,snapshot):
        text=render_progress(snapshot).replace('\n',' · ')
        if text==self.last:return
        self.last=text
        if self.output.isatty():
            self.open_line=snapshot.get('status')=='running'
            width=max(1,shutil.get_terminal_size((80,24)).columns-1)
            self.output.write('\r\x1b[2K'+text[:width]+ ('' if self.open_line else '\n'))
        else:self.output.write(text+'\n')
        self.output.flush()
    def close(self):
        if self.open_line:
            self.output.write('\n');self.output.flush();self.open_line=False

class ProgressCards:
    """Persist send intent first. Uncertain sends require explicit reconciliation."""
    def __init__(self,home,send,edit,channel,target,authorized=None,rollover_seconds=None,min_edit_interval=.8):
        if channel not in ('telegram','discord','whatsapp'):raise ValueError('Invalid progress channel')
        if rollover_seconds is not None and (not isinstance(rollover_seconds,(int,float)) or not math.isfinite(rollover_seconds) or rollover_seconds<=0):raise ValueError('Invalid rollover interval')
        if not isinstance(min_edit_interval,(int,float)) or not math.isfinite(min_edit_interval) or min_edit_interval<0:raise ValueError('Invalid edit interval')
        self.last_edit={};self.min_edit_interval=min_edit_interval
        self.send=send; self.edit=edit; self.channel=channel; self.target=hashlib.sha256(str(target).encode()).hexdigest(); self.authorized=authorized or (lambda:True); self.rollover=rollover_seconds
        home=Path(home); home.mkdir(parents=True,exist_ok=True)
        path=home/'progress-deliveries.db'
        if path.is_symlink():raise ValueError('Unsafe progress delivery database')
        fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600); os.close(fd); os.chmod(path,0o600)
        self.db=sqlite3.connect(path,check_same_thread=False,timeout=5); self.lock=threading.RLock()
        self.db.execute('CREATE TABLE IF NOT EXISTS cards (run TEXT, channel TEXT, target TEXT, state TEXT, message TEXT, started REAL, text TEXT, PRIMARY KEY(run,channel,target))'); self.db.commit()
    def __call__(self,snapshot):
        run=snapshot.get('run_id')
        if not isinstance(run,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',run):return
        text=render_progress(snapshot)
        with self.lock:
            if not self.authorized():return
            key=(run,self.channel,self.target)
            row=self.db.execute('SELECT state,message,started,text FROM cards WHERE run=? AND channel=? AND target=?',key).fetchone()
            if row and row[0] in ('creating','uncertain'):return
            rollover=row and self.rollover is not None and time.time()-row[2]>=self.rollover
            if not row or rollover:
                # Persist intent and commit before any side effect; creation is never retried.
                if row:
                    cursor=self.db.execute('UPDATE cards SET state=?,message=NULL,started=?,text=? WHERE run=? AND channel=? AND target=? AND state=? AND started=?',('creating',time.time(),text,*key,row[0],row[2]))
                else:
                    cursor=self.db.execute('INSERT OR IGNORE INTO cards VALUES (?,?,?,?,?,?,?)',(*key,'creating',None,time.time(),text))
                self.db.commit()
                if cursor.rowcount!=1:return
                try:
                    if not self.authorized():raise RuntimeError('Authorization revoked')
                    mid=self.send(text)
                    if type(mid) not in (str,int) or not str(mid) or len(str(mid))>256:raise ValueError('Invalid message identifier')
                except Exception:
                    self.db.execute('UPDATE cards SET state=? WHERE run=? AND channel=? AND target=?',('uncertain',*key)); self.db.commit(); raise RuntimeError('Progress message creation uncertain; inspect deliveries before retrying') from None
                self.db.execute('UPDATE cards SET state=?,message=? WHERE run=? AND channel=? AND target=?',('sent',json.dumps(mid),*key)); self.db.commit();self.last_edit[run]=time.monotonic()
            elif text!=row[3] or row[0]=='edit_failed':
                force=snapshot.get('status')!='running' or snapshot.get('phase') in ('awaiting_approval','needs_reconciliation','interrupted','completed','failed','step_limit')
                if not force and time.monotonic()-self.last_edit.get(run,float('-inf'))<self.min_edit_interval:return
                self.last_edit[run]=time.monotonic()
                try:
                    if not self.authorized():return
                    self.edit(json.loads(row[1]),text)
                except Exception:
                    self.db.execute('UPDATE cards SET state=? WHERE run=? AND channel=? AND target=?',('edit_failed',*key)); self.db.commit();raise RuntimeError('Progress message edit failed') from None
                self.db.execute('UPDATE cards SET state=?,text=? WHERE run=? AND channel=? AND target=?',('sent',text,*key));self.db.commit()
    def deliveries(self):
        with self.lock:
            rows=self.db.execute('SELECT run,state FROM cards WHERE channel=? AND target=? ORDER BY started DESC LIMIT 100',(self.channel,self.target)).fetchall()
            return [{'run_id':r[0],'channel':self.channel,'state':r[1]} for r in rows]
    def resolve(self,run_id,action,message_id=None):
        if action not in ('retry','sent'):raise ValueError('Invalid progress resolution')
        if action=='sent' and (type(message_id) not in (str,int) or not str(message_id) or len(str(message_id))>256):raise ValueError('Message identifier required')
        with self.lock:
            if action=='sent':
                self.db.execute("UPDATE cards SET state='sent',message=? WHERE run=? AND channel=? AND target=? AND state IN ('creating','uncertain')",(json.dumps(message_id),run_id,self.channel,self.target));self.db.commit();return
            self.db.execute("DELETE FROM cards WHERE run=? AND channel=? AND target=? AND state IN ('creating','uncertain')",(run_id,self.channel,self.target));self.db.commit()
    def close(self):
        with self.lock:self.db.close()

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class _HTTP:
    def __init__(self,timeout):
        if not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not 0<timeout<=30:raise ValueError('Invalid progress timeout')
        self.timeout=timeout;self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
    def request(self,url,payload,method='POST'):
        req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method=method)
        try:
            with self.opener.open(req,timeout=self.timeout) as response:raw=response.read(65537)
            if len(raw)>65536:raise ValueError()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            exc.close();raise RuntimeError('Progress transport request failed') from None
        except Exception:raise RuntimeError('Progress transport request failed') from None

class DiscordWebhook(_HTTP):
    def __init__(self,url,timeout=5):
        p=urllib.parse.urlsplit(url)
        if p.scheme!='https' or p.netloc not in ('discord.com','discordapp.com') or p.query or p.fragment or not re.fullmatch(r'/api(?:/v[0-9]+)?/webhooks/[0-9]+/[A-Za-z0-9_-]+',p.path):raise ValueError('Invalid Discord webhook URL')
        super().__init__(timeout);self.url=url
    def send(self,text):
        data=self.request(self.url+'?wait=true',{'content':text[:2000],'allowed_mentions':{'parse':[]}})
        if not isinstance(data,dict) or not isinstance(data.get('id'),str) or not data['id'].isdigit():raise RuntimeError('Invalid progress message response')
        return data['id']
    def edit(self,message_id,text):
        if not str(message_id).isdigit():raise ValueError('Invalid progress message identifier')
        self.request(self.url+'/messages/'+str(message_id),{'content':text[:2000],'allowed_mentions':{'parse':[]}},'PATCH')

class WhatsAppBridge(_HTTP):
    def __init__(self,url,chat_id,timeout=5):
        p=urllib.parse.urlsplit(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment or (p.scheme=='http' and p.hostname not in ('localhost','127.0.0.1','::1')):raise ValueError('Invalid WhatsApp bridge URL')
        if not isinstance(chat_id,str) or not chat_id or len(chat_id)>256:raise ValueError('Invalid WhatsApp destination')
        super().__init__(timeout);self.url=url.rstrip('/');self.chat=chat_id
    def send(self,text):
        data=self.request(self.url+'/send',{'chatId':self.chat,'message':text})
        if not isinstance(data,dict) or data.get('ok') is not True or type(data.get('messageId')) not in (str,int):raise RuntimeError('Invalid progress message response')
        return data['messageId']
    def edit(self,message_id,text):
        data=self.request(self.url+'/edit',{'chatId':self.chat,'messageId':message_id,'message':text})
        if not isinstance(data,dict) or data.get('ok') is not True:raise RuntimeError('Progress edit rejected')
