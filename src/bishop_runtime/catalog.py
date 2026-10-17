"""Bounded, read-only discovery. Model IDs are never guessed or cached fallbacks."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from .provider import HTTPProvider

MAX_BYTES = 4_000_000
MAX_MODELS = 10000

class CatalogError(ValueError):
    pass

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _get(url, headers, timeout, text=False):
    try:
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError()
        if parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1'):
            raise ValueError()
        request=urllib.request.Request(url,headers=headers,method='GET')
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(request,timeout=timeout) as response:
            body=response.read(MAX_BYTES+1)
        if len(body)>MAX_BYTES: raise CatalogError('model catalog exceeds size limit')
        return body.decode('utf-8') if text else json.loads(body)
    except CatalogError:
        raise
    except urllib.error.HTTPError as error:
        error.close()
        raise CatalogError('model catalog unavailable; check endpoint and credentials, or retry') from None
    except (OSError,ValueError,TypeError,urllib.error.URLError):
        raise CatalogError('model catalog unavailable; check endpoint and credentials, or retry') from None

class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=None; self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr': self.row=[]
        elif tag in ('td','th') and self.row is not None: self.cell=[]
    def handle_data(self,data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip()); self.cell=None
        elif tag=='tr' and self.row is not None:
            self.rows.append(self.row); self.row=None

def _routes(html):
    parser=_Tables()
    try:
        parser.feed(html)
    except (ValueError, TypeError, AttributeError):
        raise CatalogError('invalid provider routing catalog') from None
    result={}
    for row in parser.rows:
        if len(row)<3: continue
        model=row[1]
        match=re.fullmatch(r'https://opencode\.ai(/inference/(?:go/)?(?:openai|anthropic)/v1)/(responses|messages|chat/completions)',row[2].strip())
        if not match or not _safe(model,200): continue
        result[model]={'kind':{'responses':'responses','messages':'anthropic','chat/completions':'compatible'}[match[2]],'base_url':'https://opencode.ai'+match[1]}
    return result

def _safe(value,maximum=256):
    return isinstance(value,str) and 0<len(value)<=maximum and all(ord(c)>=32 and ord(c)!=127 for c in value)

def _text_candidate(row,provider):
    if provider=='openrouter' and row['id'].endswith(':batch'): return False
    architecture=row.get('architecture',{})
    if isinstance(architecture,dict):
        outputs=architecture.get('output_modalities')
        if isinstance(outputs,list) and (not outputs or any(x!='text' for x in outputs)): return False
    supported=row.get('supported_parameters')
    if isinstance(supported,list) and 'tools' not in supported: return False
    if row.get('tool_call') is False: return False
    if provider=='openai':
        name=row['id'].lower()
        if any(x in name for x in ('audio','realtime','transcribe','tts','embedding','image','instruct','search','moderation')): return False
        return bool(re.match(r'^(gpt-|chatgpt-|o[134](?:-|$))',name))
    return True

def _free(row):
    if row['id'].endswith(('-free',':free')): return True
    pricing=row.get('pricing')
    if not isinstance(pricing,dict): return False
    try:
        return all(float(pricing[k])==0 for k in ('prompt','completion'))
    except (KeyError,ValueError,TypeError): return False

def discover_models(provider_id,base_url,kind='compatible',api_key=None,timeout=15):
    """Return selectable {id,label,kind,base_url,free} records, no inference calls."""
    if not isinstance(timeout,(int,float)) or not 0<timeout<=60:
        raise CatalogError('invalid catalog timeout')
    try:
        HTTPProvider(base_url, 'catalog-check', api_key=api_key, timeout=timeout)
    except (ValueError, TypeError, AttributeError):
        raise CatalogError('invalid catalog endpoint or credential') from None
    headers={'Accept':'application/json','User-Agent':'bishop-runtime/0.2'}
    opencode=provider_id in ('opencode','opencode-claude','opencode-go','opencode-free')
    if api_key and not opencode:
        if kind=='anthropic' or provider_id=='anthropic':
            headers['x-api-key']=api_key
        else: headers['Authorization']='Bearer '+api_key
    if kind=='anthropic' or provider_id=='anthropic': headers['anthropic-version']='2023-06-01'
    go=provider_id=='opencode-go'
    url=('https://opencode.ai/inference/'+('go/' if go else '')+'v1/models') if opencode else base_url.rstrip('/')+'/models'
    rows=[]
    for page in range(20):
        data=_get(url,headers,timeout)
        if not isinstance(data,dict) or not isinstance(data.get('data'),list): raise CatalogError('invalid model catalog')
        rows.extend(data['data'])
        if len(rows)>MAX_MODELS: raise CatalogError('model catalog exceeds model limit')
        if (provider_id!='anthropic' and kind!='anthropic') or not data.get('has_more'): break
        cursor=data.get('last_id')
        if not _safe(cursor): raise CatalogError('invalid model catalog cursor')
        url=base_url.rstrip('/')+'/models?'+urllib.parse.urlencode({'after_id':cursor,'limit':100})
    else: raise CatalogError('model catalog pagination limit reached')
    routes=None
    if opencode:
        doc='https://opencode.ai/v2/docs/console/'+('go/' if go else 'models/')
        routes=_routes(_get(doc,{'Accept':'text/html','User-Agent':headers['User-Agent']},timeout,text=True))
        if not routes: raise CatalogError('provider routing catalog unavailable; retry')
    result=[]; seen=set()
    for row in rows:
        if not isinstance(row,dict) or not _safe(row.get('id'),200): continue
        name=row['id']
        if name in seen or not _text_candidate(row,provider_id): continue
        route={'kind':kind,'base_url':base_url.rstrip('/')}
        # Current GPT and o-series models use Responses, including Responses-only
        # variants. Catalog IDs stay live; this is transport family policy only.
        if provider_id=='openai' and re.match(r'^(gpt-(?:[5-9]|[1-9][0-9]|4[.o])|o[134](?:-|$))',name.lower()):
            route['kind']='responses'
        if routes is not None:
            if name not in routes: continue
            route=routes[name]
            if provider_id=='opencode-claude' and route['kind']!='anthropic': continue
            if provider_id=='opencode-free' and not _free(row): continue
        label=row.get('display_name') or row.get('name') or name
        if not _safe(label): label=name
        result.append({'id':name,'label':label,**route,'free':_free(row)})
        seen.add(name)
    return result
