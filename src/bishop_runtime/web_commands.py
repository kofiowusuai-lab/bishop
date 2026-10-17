"""Direct research diagnostics without a model request."""
import json
import os
from pathlib import Path
import tempfile

from .config import init_home,load_config,validate_web
from .menu import choose
from .operator import _configuration
from .search import WebSearch
from .web import WebClient,WebError


def status(home):
    settings=_configuration(Path(home))['web']
    return {'enabled':settings['enabled'],'provider':settings['provider'],
            'credential_required':settings['provider']=='brave',
            'credential_configured':bool(os.environ.get(settings['api_key_env'])) if settings['provider']=='brave' else None,
            'key_environment':settings['api_key_env'] if settings['provider']=='brave' else None,
            'tools':['web_search','web_read'] if settings['enabled'] else [],'network':'not contacted'}


def configure(home):
    init_home(home);config=load_config(home);settings=config['web']
    action=choose('Web research',[('duckduckgo','DuckDuckGo Lite · no key; public service may challenge'),
        ('brave','Brave Search API · your search key; provider charges may apply'),
        ('disable','Disable web research'),('back','Back / cancel')])
    if action in (None,'back'):return {'changed':False}
    if action=='disable':settings['enabled']=False
    else:settings['enabled']=True;settings['provider']=action
    validate_web(settings)
    path=Path(home)/'config.json'
    if path.is_symlink():raise ValueError('configuration must not be a symlink')
    fd,temporary=tempfile.mkstemp(prefix='.web-config-',dir=home)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(config,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.chmod(temporary,0o600);os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    value=status(home);value['changed']=True
    value['note']='Restart Bishop or its gateway to load the settings.'
    if settings['provider']=='brave':value['note']+=' Supply the search key through the configured environment variable; no model-provider keys are imported.'
    return value


def execute(home,args):
    operation=args.web_command or 'status'
    if operation=='status':return status(home),0
    if operation=='configure':return configure(home),0
    settings=_configuration(Path(home))['web']
    if not settings['enabled']:return {'ok':False,'error':'web_disabled','message':'Enable web research with bishop web configure.'},1
    client=WebClient(timeout=settings['timeout'])
    try:
        if operation=='read':return client.read(args.url,max_chars=settings['page_chars']),0
        search=WebSearch(client,provider=settings['provider'],api_key=os.environ.get(settings['api_key_env']) if settings['provider']=='brave' else None)
        return search.search(' '.join(args.query),limit=settings['max_results']),0
    except WebError as error:
        return {'ok':False,'error':error.code,'message':error.message,'retryable':error.retryable},1
