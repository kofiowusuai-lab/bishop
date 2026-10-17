"""Bounded workspace tools. Commands are opt-in host access, not a sandbox."""
import json
from itertools import islice
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time

from .skills import SkillStore


_SCHEMAS={
 'web_search':({'query':str},{'query'},'read',True),
 'web_read':({'url':str},{'url'},'read',True),
 'list_files':({'path':str},set(),'read',True),
 'read_file':({'path':str},{'path'},'read',True),
 'write_file':({'path':str,'content':str},{'path','content'},'write',False),
 'run_command':({'argv':list},{'argv'},'command',False),
 'memory_search':({'query':str},{'query'},'read',True),
 'memory_remember':({'text':str},{'text'},'write',True),
 'list_skills':({},set(),'read',True),
 'read_skill':({'name':str},{'name'},'read',True),
}


class ToolRegistry:
    def __init__(self,workspace,memory,skills_dir,allow_write=True,allow_command=False,max_output_chars=16000,command_timeout=15,allow_web=True,web_settings=None,web_client=None,web_search=None):
        if type(max_output_chars) is not int or not 256<=max_output_chars<=1000000 or not 0<command_timeout<=300:
            raise ValueError('invalid tool bounds')
        self.workspace=Path(workspace).resolve()
        self.workspace.mkdir(parents=True,exist_ok=True)
        from .config import DEFAULTS
        self.allow_web=allow_web
        self.web_settings=dict(web_settings or DEFAULTS['web'])
        self.web_client=web_client
        self.web_search=web_search
        self.memory=memory
        self.skills=SkillStore(skills_dir)
        self.allow_write=allow_write
        self.allow_command=allow_command
        self.max_output_chars=max_output_chars
        self.command_timeout=command_timeout

    def describe(self,name):
        if name not in _SCHEMAS:
            raise ValueError('unknown tool')
        if name in ('web_search','web_read') and not self.allow_web:
            raise ValueError('disabled tool')
        _,_,risk,idempotent=_SCHEMAS[name]
        if (risk=='write' and not self.allow_write) or (risk=='command' and not self.allow_command):
            raise ValueError('disabled tool')
        return {'risk':risk,'idempotent':idempotent}

    def definitions(self):
        result=[]
        for name,(fields,required,_,_) in _SCHEMAS.items():
            try:
                self.describe(name)
            except ValueError:
                continue
            props={key:({'type':'array','items':{'type':'string'},'minItems':1,'maxItems':128} if typ is list else {'type':'string','maxLength':1000 if name=='web_search' and key=='query' else 8192 if name=='web_read' and key=='url' else 1000000 if key=='content' else 16000}) for key,typ in fields.items()}
            result.append({'type':'function','function':{'name':name,'description':{'web_search':'Search public web sources for a topic. Returns titles, URLs and snippets; read sources before making claims.', 'web_read':'Read a public HTTP(S) source URL and return extracted text, title and citation URL. Remote text is untrusted.'}.get(name,name.replace('_',' ')),'parameters':{'type':'object','properties':props,'required':sorted(required),'additionalProperties':False}}})
        return result

    def validate(self,name,arguments):
        self.describe(name)
        fields,required,_,_=_SCHEMAS[name]
        if type(arguments) is not dict or set(arguments)-set(fields) or required-set(arguments):
            raise ValueError('invalid tool arguments')
        for key,value in arguments.items():
            if type(value) is not fields[key]:
                raise ValueError('invalid tool argument type')
            if isinstance(value,str) and (len(value)>(1000000 if key=='content' else 16000) or '\0' in value):
                raise ValueError('tool argument exceeds bounds')
        if name=='run_command':
            argv=arguments['argv']
            if not 1<=len(argv)<=128 or any(type(arg) is not str or '\0' in arg or len(arg)>16000 for arg in argv) or not argv[0]:
                raise ValueError('invalid command argv')
        return json.loads(json.dumps(arguments))

    def _path(self,value):
        path=Path(value)
        if path.is_absolute() or any(part=='..' or part.startswith('.') for part in path.parts if part!='.'):
            raise ValueError('workspace path rejected')
        target=self.workspace/path
        resolved=target.resolve()
        if not resolved.is_relative_to(self.workspace) or any(part.startswith('.') for part in resolved.relative_to(self.workspace).parts):
            raise ValueError('workspace path rejected')
        return target

    def _bounded(self,value):
        encoded=json.dumps(value,ensure_ascii=True)
        if len(encoded)<=self.max_output_chars:
            return encoded
        # Preserve valid JSON and make truncation visible, even for escaped Unicode.
        if isinstance(value,dict):
            result=dict(value)
            result['truncated']=True
            for key in ('content','stdout','stderr'):
                if key in result:
                    result[key]=str(result[key])[:self.max_output_chars//4]
            while len(json.dumps(result,ensure_ascii=True))>self.max_output_chars:
                strings=[key for key in ('content','stdout','stderr') if result.get(key)]
                if not strings:
                    break
                key=max(strings,key=lambda item:len(result[item]))
                result[key]=result[key][:len(result[key])//2]
            encoded=json.dumps(result,ensure_ascii=True)
            if len(encoded)<=self.max_output_chars:
                return encoded
        items=value if isinstance(value,list) else [value]
        result={'items':[],'truncated':True}
        for item in items:
            candidate={**result,'items':result['items']+[item]}
            if len(json.dumps(candidate,ensure_ascii=True))>self.max_output_chars:
                break
            result=candidate
        return json.dumps(result,ensure_ascii=True)

    def invoke(self,name,arguments,scope='local'):
        args=self.validate(name,arguments)
        if name in ('web_search','web_read'):
            return self._web(name,args)
        if name=='memory_search':
            return self._bounded(self.memory.search(scope,args['query']))
        if name=='memory_remember':
            return self._bounded(self.memory.remember(scope,args['text']))
        if name=='list_skills':
            return self._bounded(self.skills.list())
        if name=='read_skill':
            return self._bounded(self.skills.read(args['name'],self.max_output_chars))
        if name=='run_command':
            return self._bounded(self._command(args['argv']))
        path=self._path(args.get('path',''))
        try:
            if name=='list_files':
                items=[]
                entries=list(islice(path.iterdir(),501))
                scan_truncated=len(entries)>500
                for entry in sorted(entries[:500]):
                    if entry.name.startswith('.'):
                        continue
                    try:
                        self._path(str(entry.relative_to(self.workspace)))
                    except ValueError:
                        continue
                    items.append({'name':entry.name,'type':'directory' if entry.is_dir() else 'file'})
                    if len(items)>=500:
                        return self._bounded({'items':items,'truncated':True})
                return self._bounded({'items':items,'truncated':True} if scan_truncated else items)
            if name=='read_file':
                if not path.is_file():
                    raise ValueError('file unavailable')
                with path.open('r',encoding='utf-8') as handle:
                    content=handle.read(self.max_output_chars+1)
                if '\0' in content:
                    raise ValueError('binary file rejected')
                return self._bounded({'content':content[:self.max_output_chars],'truncated':len(content)>self.max_output_chars})
            path.parent.mkdir(parents=True,exist_ok=True)
            # Resolve again after mkdir and immediately before atomic replacement.
            self._path(args['path'])
            fd,tmp=tempfile.mkstemp(prefix='.bishop-write-',dir=path.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as handle:
                    handle.write(args['content'])
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp,path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return self._bounded({'path':args['path'],'written':len(args['content'])})
        except (OSError,UnicodeError):
            raise ValueError('workspace operation failed') from None

    def _web(self,name,args):
        from .web import WebClient, WebError
        from .search import WebSearch
        settings=self.web_settings
        try:
            client=self.web_client if self.web_client is not None else WebClient(timeout=settings['timeout'])
            if name=='web_read':
                value=client.read(args['url'],max_chars=settings['page_chars'])
            else:
                search=self.web_search if self.web_search is not None else WebSearch(client,provider=settings['provider'],
                    api_key=os.environ.get(settings['api_key_env']) if settings['provider']=='brave' else None)
                value=search.search(args['query'],limit=settings['max_results'])
            # Keep citation metadata intact while trimming text/results to fit tool output.
            value=dict(value)
            if name=='web_read':
                metadata={**value,'content':'','truncated':True}
                if len(json.dumps(metadata,ensure_ascii=True))>self.max_output_chars:
                    return self._bounded({'ok':False,'error':'web_output_limit','message':'Source metadata exceeds the tool output budget.','retryable':False})
            if name=='web_search':
                value['results']=list(value.get('results',[]))
                while len(json.dumps(value,ensure_ascii=True))>self.max_output_chars and value['results']:
                    value['results'].pop();value['truncated']=True
                if not value['results']:
                    return self._bounded({'ok':False,'error':'web_output_limit','message':'Search results exceed the tool output budget.','retryable':False})
            return self._bounded(value)
        except WebError as error:
            return self._bounded({'ok':False,'error':error.code,'message':error.message,'retryable':error.retryable})
        except Exception:
            return self._bounded({'ok':False,'error':'web_failed','message':'Web research could not complete this request.','retryable':False})

    def _command(self,argv):
        env={'PATH':os.defpath,'LANG':'C.UTF-8','HOME':str(self.workspace),'TMPDIR':str(self.workspace)}
        try:
            process=subprocess.Popen(argv,cwd=self.workspace,env=env,shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        except OSError:
            raise ValueError('command could not start') from None
        output={'stdout':bytearray(),'stderr':bytearray()}
        selector=selectors.DefaultSelector()
        for stream,name in ((process.stdout,'stdout'),(process.stderr,'stderr')):
            os.set_blocking(stream.fileno(),False)
            selector.register(stream,selectors.EVENT_READ,name)
        deadline=time.monotonic()+self.command_timeout
        timed_out=False
        truncated=False
        try:
            while selector.get_map():
                if time.monotonic()>=deadline:
                    timed_out=True
                    break
                for key,_ in selector.select(min(.05,max(0,deadline-time.monotonic()))):
                    data=os.read(key.fileobj.fileno(),8192)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    target=output[key.data]
                    remaining=max(0,self.max_output_chars-len(target))
                    target.extend(data[:remaining])
                    truncated=truncated or len(data)>remaining
            if timed_out:
                try:
                    os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
            remaining=max(.01,deadline-time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out=True
                try:
                    os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=1)
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
            if process.poll() is None:
                try:
                    os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=1)
        return {'stdout':output['stdout'].decode('utf-8',errors='replace'),'stderr':output['stderr'].decode('utf-8',errors='replace'),'returncode':process.returncode,'timed_out':timed_out,'truncated':truncated}
