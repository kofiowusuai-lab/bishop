"""Optional, independently operated Telegram long-poll channel."""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from .channel_state import ChannelState

class TelegramError(RuntimeError): pass
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

class TelegramClient:
    def __init__(self,token,base_url='https://api.telegram.org',timeout=35):
        parsed=urllib.parse.urlsplit(base_url)
        if not isinstance(token,str) or not token or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-' for c in token): raise ValueError('Invalid Telegram token')
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment: raise ValueError('Invalid Telegram origin')
        if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'): raise ValueError('Telegram requires HTTPS outside loopback')
        if not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not 0<timeout<=120: raise ValueError('Invalid Telegram timeout')
        self.url=base_url.rstrip('/')+'/bot'+token+'/'; self.timeout=timeout
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
    def _call(self,method,payload):
        req=urllib.request.Request(self.url+method,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
        try:
            with self.opener.open(req,timeout=self.timeout) as response: raw=response.read(2_000_001)
            if len(raw)>2_000_000: raise TelegramError('Telegram response too large')
            data=json.loads(raw)
            if not isinstance(data,dict) or data.get('ok') is not True: raise TelegramError('Telegram API rejected request')
            return data.get('result')
        except urllib.error.HTTPError as exc:
            exc.close()
            raise TelegramError('Telegram HTTP request rejected') from None
        except TelegramError: raise
        except Exception: raise TelegramError('Telegram transport or response failure') from None
    def get_updates(self,offset,timeout=25):
        result=self._call('getUpdates',{'offset':offset,'timeout':min(max(timeout,0),25),'limit':100,'allowed_updates':['message']})
        if not isinstance(result,list) or len(result)>100: raise TelegramError('Invalid Telegram updates')
        return result
    def send_message(self,chat_id,text):
        if not isinstance(text,str) or not text or len(text.encode('utf-16-le'))//2>4096: raise ValueError('Telegram text exceeds message limit')
        result=self._call('sendMessage',{'chat_id':chat_id,'text':text})
        if not isinstance(result,dict) or type(result.get('message_id')) is not int: raise TelegramError('Invalid Telegram send response')
        return result

def _chunks(text):
    current=[]; count=0
    for char in text:
        n=2 if ord(char)>0xffff else 1
        if count+n>4096: yield ''.join(current); current=[]; count=0
        current.append(char); count+=n
    if current: yield ''.join(current)

def _render(run):
    if run.get('status')=='completed': return run.get('output') or '(Empty response)'
    result=f"Run {run['id']}: {run['status']}"
    for call in run.get('pending',[]): result+=f"\nApproval required: {call['name']} {json.dumps(call['arguments'],ensure_ascii=False)}\n/approve {run['id']} {call['id']}"
    return result

class TelegramService:
    def __init__(self,home,client,runtime,allowed_users):
        if not allowed_users or any(type(u) is not int or u<=0 for u in allowed_users): raise ValueError('Positive numeric Telegram allowlist required')
        self.client=client; self.runtime=runtime; self.allowed=set(allowed_users)
        try: self.state=ChannelState(home)
        except ValueError as exc: raise TelegramError(str(exc)) from None
    def _authorize(self,u):
        m=u.get('message')
        if not isinstance(m,dict): return None
        sender=m.get('from'); chat=m.get('chat'); text=m.get('text')
        if not isinstance(sender,dict) or not isinstance(chat,dict): return None
        if type(sender.get('id')) is not int or sender['id'] not in self.allowed or sender.get('is_bot') or chat.get('type')!='private' or type(chat.get('id')) is not int or not isinstance(text,str) or not text or len(text)>16000: return None
        return {'user':sender['id'],'chat':chat['id'],'text':text}
    def _handle(self,p,recover=False):
        actor=f"telegram:{p['user']}"; session=f"telegram:{p['chat']}"; text=p['text']; parts=text.split()
        if recover:
            active=self.runtime.active(session,actor=actor)
            return _render(active) if active else 'Previous update was interrupted. Check /status before explicitly resubmitting.'
        if text.startswith('/'):
            command=parts[0].split('@',1)[0]
            if command=='/start': return 'Bishop is ready. Send a task. Commands: /status, /approve RUN CALL, /deny RUN CALL, /resume RUN.'
            if command=='/status':
                if len(parts)>2: return 'Usage: /status [RUN]'
                run=self.runtime.status(parts[1]) if len(parts)==2 else self.runtime.active(session,actor=actor)
                if run and run['actor']!=actor: return 'Run is not owned by this Telegram user.'
                return _render(run) if run else 'No active run in this chat.'
            if command in ('/approve','/deny','/resume'):
                if len(parts)!=(2 if command=='/resume' else 3): return 'Usage: '+command+' RUN'+(' CALL' if command!='/resume' else '')
                run=self.runtime.status(parts[1])
                if run['actor']!=actor: return 'Run is not owned by this Telegram user.'
                if command=='/resume': return _render(self.runtime.resume(parts[1],actor=actor))
                run=getattr(self.runtime,command[1:])(parts[1],parts[2],actor=actor)
                return _render(run)+'\nUse /resume '+run['id']+' to continue.'
            return 'Unknown command.'
        active=self.runtime.active(session,actor=actor)
        if active: return 'An active run needs attention. '+_render(active)
        return _render(self.runtime.run(session,text,actor=actor))
    def poll_once(self):
        self.state.renew()
        updates=self.client.get_updates(self.state.offset(),timeout=25)
        self.state.ingest(updates,self._authorize)
        processed=0
        for row in self.state.queued():
            self.state.renew(); payload=json.loads(row['payload'])
            if payload['user'] not in self.allowed:
                self.state.mark(row['id'],'revoked'); continue
            self.state.mark(row['id'],'processing')
            try: output=self._handle(payload,recover=row['status']=='recover')
            except Exception: output='Bishop could not complete this update. Check local run status; no automatic retry was made.'
            self.state.finish(row['id'],payload['chat'],list(_chunks(output))); processed+=1
        sent=0
        for delivery in self.state.deliveries():
            if delivery['status']!='pending': continue
            if not self.state.authorized_delivery(delivery['update_id'],self.allowed):
                self.state.delivery_status(delivery['id'],'revoked'); continue
            if self.state.delivery_blocked(delivery['id'],delivery['update_id']): continue
            self.state.renew(); self.state.delivery_status(delivery['id'],'sending')
            try: self.client.send_message(delivery['chat_id'],delivery['text'])
            except Exception: self.state.delivery_status(delivery['id'],'uncertain')
            else: self.state.delivery_status(delivery['id'],'sent'); sent+=1
        return {'processed':processed,'sent':sent,'offset':self.state.offset()}
    def deliveries(self): return self.state.deliveries()
    def resolve_delivery(self,delivery_id,action):
        if action not in ('sent','retry'): raise ValueError('Action must be sent or retry')
        matches=[d for d in self.state.deliveries() if d['id']==delivery_id]
        if not matches or matches[0]['status']!='uncertain': raise ValueError('Delivery is not uncertain')
        self.state.delivery_status(delivery_id,'sent' if action=='sent' else 'pending')
    def serve(self):
        failures=0
        while True:
            try: self.poll_once(); failures=0
            except (TelegramError,OSError,TimeoutError):
                failures+=1
                if failures>=3: raise TelegramError('Telegram polling stopped after three transport failures') from None
                time.sleep(2**failures)
    def close(self): self.state.close()
