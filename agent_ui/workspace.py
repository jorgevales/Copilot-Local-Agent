"""Local authenticated workspace. No model API, telemetry, or execution bypass."""
from __future__ import annotations
import argparse
import importlib
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
MAX_BODY = 1024 * 1024

class Workspace:
    def __init__(self):
        self.lock = threading.RLock()
        self.events = []
        self.sequence = 0
        self.pending = {}
        self.runtime = None
        self.busy = False
        self.capabilities = {}

    def emit(self, kind, payload):
        # Runtime supplies safe, redacted UI content. Raw private reasoning is not accepted.
        if kind not in {'user','copilot','system','warning','error','status','plan','tool','context','model','artifact','session','connection'}:
            raise ValueError('Unsupported event type')
        if not isinstance(payload, dict):
            raise ValueError('Event payload must be an object')
        value = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        if len(json.dumps(value)) > MAX_BODY:
            raise ValueError('UI event exceeds size limit')
        with self.lock:
            self.sequence += 1
            self.events.append({'id': self.sequence, 'time': time.time(), 'kind': kind, 'payload': value})
            self.events = self.events[-5000:]
            if kind == 'status':
                if value.get('state') == 'action_active': self.busy = True
                elif value.get('state') == 'awaiting_input': self.busy = False

    def request_approval(self, preview):
        """Blocking callback for the runtime worker; exact scope remains backend-owned."""
        snapshot = json.loads(json.dumps(preview, ensure_ascii=False, allow_nan=False))
        if not snapshot.get('plan_hash') or not snapshot.get('call_hash'):
            raise ValueError('Approval requires backend plan and call hashes')
        ticket = secrets.token_urlsafe(24)
        gate = threading.Event()
        with self.lock:
            self.pending[ticket] = {'preview': snapshot, 'gate': gate, 'decision': None}
        self.emit('status', {'state': 'awaiting_approval', 'summary': 'Review the exact pending execution.'})
        # No automatic approval or timeout acceptance.
        gate.wait()
        with self.lock:
            item = self.pending.pop(ticket)
        return item['decision']

    def decide(self, ticket, decision, plan_hash, call_hash):
        if decision not in {'deny', 'once', 'plan'}:
            raise ValueError('Invalid decision')
        with self.lock:
            item = self.pending.get(ticket)
            if item is None or item['decision'] is not None:
                raise ValueError('Approval is no longer pending')
            if item['preview']['plan_hash'] != plan_hash or item['preview']['call_hash'] != call_hash:
                raise ValueError('Approval identity changed')
            item['decision'] = decision
            item['gate'].set()

    def snapshot(self, after=0):
        with self.lock:
            approvals = [{'ticket': key, 'preview': item['preview']} for key,item in self.pending.items() if item['decision'] is None]
            return {'events': [e for e in self.events if e['id'] > after],
                    'cursor': self.sequence, 'approvals': approvals, 'busy': self.busy,
                    'capabilities': self.capabilities, 'runtime_connected': self.runtime is not None}

    def submit(self, text):
        if not isinstance(text,str) or not text.strip() or len(text) > 100000:
            raise ValueError('Enter a request of at most 100,000 characters')
        with self.lock:
            if self.runtime is None:
                raise ValueError('Live runtime is not connected. No prompt was sent.')
            if self.busy:
                raise ValueError('A turn is active; preserve your draft until it completes.')
            self.busy = True
        self.emit('user', {'text':text})
        def run():
            try:
                self.runtime.submit(text)
            except Exception:
                # Never expose raw exception paths, secrets, or browser URLs.
                self.emit('error', {'summary':'The runtime reported an error.',
                    'details':'Inspect the retained backend diagnostic report. No automatic replay was requested.'})
            finally:
                with self.lock:
                    self.busy = False
        threading.Thread(target=run,daemon=True).start()

    def close(self):
        with self.lock:
            for item in self.pending.values():
                if item['decision'] is None:
                    item['decision']='deny'; item['gate'].set()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass  # Never log bearer tokens or request contents.

    def headers_common(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def reply(self,code,value):
        data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(code); self.headers_common()
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)

    def valid_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def authorized(self):
        value=self.headers.get('Authorization','')
        return self.valid_host() and secrets.compare_digest(value,'Bearer '+self.server.token)

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403,{'error':'Invalid host'})
        parsed=urlsplit(self.path)
        if parsed.path=='/api/state':
            if not self.authorized(): return self.reply(401,{'error':'Unauthorized'})
            try: after=max(0,int(parse_qs(parsed.query).get('after',['0'])[0]))
            except ValueError: return self.reply(400,{'error':'Invalid cursor'})
            return self.reply(200,self.server.workspace.snapshot(after))
        paths={'/':'index.html','/app.js':'app.js','/styles.css':'styles.css'}
        name=paths.get(parsed.path)
        if name is None: return self.reply(404,{'error':'Not found'})
        data=(ROOT/'web'/name).read_bytes()
        self.send_response(200); self.headers_common()
        self.send_header('Content-Type',{'html':'text/html','js':'text/javascript','css':'text/css'}[name.rsplit('.',1)[1]]+'; charset=utf-8')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

    def do_POST(self):
        origin=f'http://127.0.0.1:{self.server.server_port}'
        if not self.authorized() or self.headers.get('Origin') != origin:
            return self.reply(403,{'error':'Unauthorized request'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=MAX_BODY: raise ValueError('Invalid request size')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ValueError('JSON required')
            body=json.loads(self.rfile.read(size))
            if not isinstance(body,dict): raise ValueError('Object required')
            route=urlsplit(self.path).path
            ws=self.server.workspace
            if route=='/api/submit': ws.submit(body.get('text'))
            elif route=='/api/approval': ws.decide(body.get('ticket'),body.get('decision'),body.get('plan_hash'),body.get('call_hash'))
            elif route=='/api/action':
                action=body.get('action')
                if action not in {'stop','new_session','attach','set_model','resume'} or not ws.capabilities.get(action):
                    raise ValueError('Action is not supported by the connected runtime')
                with ws.lock:
                    if action!='stop' and ws.busy: raise ValueError('Wait for the active turn to finish')
                    ws.busy=True
                # These methods must enqueue safely; they must not execute work in the HTTP handler.
                try: ws.runtime.action(action,body.get('value'))
                except Exception:
                    with ws.lock: ws.busy=False
                    raise
            else: return self.reply(404,{'error':'Not found'})
            self.reply(200,{'ok':True})
        except (ValueError,TypeError,json.JSONDecodeError) as exc:
            self.reply(400,{'error':str(exc)})
        except Exception:
            self.reply(500,{'error':'Backend action failed. No automatic replay was requested.'})

def main():
    parser=argparse.ArgumentParser(description='Local Copilot Agent graphical workspace')
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--runtime',help='Reviewed project module exporting create_runtime(emit, request_approval)')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    ws=Workspace()
    if args.runtime:
        module=importlib.import_module(args.runtime)
        runtime=module.create_runtime(ws.emit,ws.request_approval)
        capabilities=dict(runtime.capabilities)
        if not callable(runtime.submit) or not callable(runtime.action):
            raise TypeError('Runtime must expose submit and action methods')
        ws.runtime=runtime;ws.capabilities=capabilities
        ws.emit('connection',{'summary':'Local runtime connected','state':'connected'})
    else:
        ws.emit('system',{'summary':'Workspace ready. Live agent integration is not connected.',
                         'details':'No model request, browser navigation, approval, or tool execution has occurred.'})
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.workspace=ws;server.token=secrets.token_urlsafe(32)
    address=f'http://127.0.0.1:{server.server_port}/#token={server.token}'
    print('Local workspace started. Keep this window open. Ctrl+C closes the UI server.')
    if not args.no_browser: webbrowser.open(address)
    else: print(address) # Explicit local launch only; never persisted or logged by HTTP.
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        ws.close()
        if ws.runtime is not None and callable(getattr(ws.runtime,'close',None)):
            ws.runtime.close()
        server.server_close()

if __name__=='__main__': main()
