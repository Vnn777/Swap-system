import csv
import io
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE = Path(__file__).resolve().parent
DB = Path(os.getenv('DATABASE_PATH', str(BASE / 'instance' / 'turnos.db')))
DB.parent.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', '0') == '1', PERMANENT_SESSION_LIFETIME=timedelta(hours=10), MAX_CONTENT_LENGTH=30000)
ITEMS = ['Organização e Limpeza','Insumos disponíveis','Manipulado e acabado liberados','Reatores cheios, quando não possível, kanban disponível','Passagem de turno líder a líder de linha','Apontamento nas linhas atualizado','IBCs disponíveis para envase','Paletes disponíveis para produção','Paletes quebrados no descarte']
STATUSES = {'ok', 'pending', 'na'}

def db():
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    return conn

def init_db():
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL COLLATE NOCASE UNIQUE,full_name TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','user')),active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,shift_date TEXT NOT NULL,shift TEXT NOT NULL,outgoing TEXT NOT NULL,incoming TEXT NOT NULL,sector TEXT NOT NULL,notes TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS record_items(record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,item_number INTEGER NOT NULL,status TEXT NOT NULL,note TEXT NOT NULL,PRIMARY KEY(record_id,item_number));''')

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def clean(v, n=100): return v.strip() if isinstance(v,str) and len(v.strip()) <= n else ''
def user():
    uid=session.get('uid')
    if not uid: return None
    with db() as c: return c.execute('SELECT id,username,full_name,role FROM users WHERE id=? AND active=1',(uid,)).fetchone()

def auth(fn):
    @wraps(fn)
    def wrap(*a,**k):
        if not user(): return jsonify(error='Sessão encerrada. Entre novamente.'),401
        if request.method in ('POST','PUT','PATCH','DELETE') and request.headers.get('X-CSRF-Token') != session.get('csrf'):
            return jsonify(error='Token de segurança inválido. Atualize a página.'),403
        return fn(*a,**k)
    return wrap

def admin(fn):
    @wraps(fn)
    @auth
    def wrap(*a,**k):
        if user()['role']!='admin': return jsonify(error='Acesso reservado ao administrador.'),403
        return fn(*a,**k)
    return wrap

@app.after_request
def headers(resp):
    resp.headers['X-Content-Type-Options']='nosniff'
    resp.headers['X-Frame-Options']='DENY'
    resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    resp.headers['Cache-Control']='no-store'
    resp.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return resp

@app.get('/')
def home():
    u=user()
    if not u: return redirect(url_for('login'))
    session.setdefault('csrf',secrets.token_urlsafe(32))
    return render_template('index.html',me=dict(u),csrf=session['csrf'],items=ITEMS)

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='GET': return render_template('login.html',error=None)
    username=clean(request.form.get('username'),50)
    password=request.form.get('password','')
    with db() as c: u=c.execute('SELECT * FROM users WHERE username=? AND active=1',(username,)).fetchone()
    if not u or not check_password_hash(u['password_hash'],password):
        return render_template('login.html',error='Usuário ou senha incorretos.'),401
    session.clear()
    session.permanent=True
    session['uid']=u['id']
    session['csrf']=secrets.token_urlsafe(32)
    return redirect(url_for('home'))

@app.post('/logout')
@auth
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get('/api/records')
@auth
def records():
    with db() as c:
        rows=c.execute('''SELECT r.*,u.full_name AS author,(SELECT COUNT(*) FROM record_items i WHERE i.record_id=r.id AND i.status='pending') AS pending_count FROM records r JOIN users u ON u.id=r.created_by ORDER BY r.id DESC LIMIT 1000''').fetchall()
    return jsonify(records=[dict(r) for r in rows])

@app.get('/api/records/<int:rid>')
@auth
def record_detail(rid):
    with db() as c:
        r=c.execute('SELECT r.*,u.full_name AS author FROM records r JOIN users u ON u.id=r.created_by WHERE r.id=?',(rid,)).fetchone()
        if not r: return jsonify(error='Registro não encontrado.'),404
        items=c.execute('SELECT item_number,status,note FROM record_items WHERE record_id=? ORDER BY item_number',(rid,)).fetchall()
    return jsonify(record=dict(r),items=[dict(i) for i in items])

@app.post('/api/records')
@auth
def save_record():
    data=request.get_json(silent=True) or {}
    date=clean(data.get('date'),10)
    shift=clean(data.get('shift'),30)
    outgoing=clean(data.get('outgoing'))
    incoming=clean(data.get('incoming'))
    sector=clean(data.get('sector'))
    notes=clean(data.get('notes'),3000)
    items=data.get('items')
    try: datetime.strptime(date,'%Y-%m-%d')
    except (ValueError,TypeError): return jsonify(error='Data inválida.'),400
    if shift not in ('1º turno','2º turno','3º turno','Administrativo') or not all((outgoing,incoming,sector)) or not isinstance(items,list) or len(items)!=9:
        return jsonify(error='Preencha todos os campos e avalie os 9 itens.'),400
    parsed=[]
    for i,entry in enumerate(items,1):
        if not isinstance(entry,dict) or entry.get('status') not in STATUSES:
            return jsonify(error=f'Avalie o item {i}.'),400
        note=clean(entry.get('note',''),500)
        if entry['status']=='pending' and not note:
            return jsonify(error=f'Descreva a pendência do item {i}.'),400
        parsed.append((i,entry['status'],note))
    with db() as c:
        cur=c.execute('INSERT INTO records(created_by,created_at,shift_date,shift,outgoing,incoming,sector,notes) VALUES(?,?,?,?,?,?,?,?)',(user()['id'],now(),date,shift,outgoing,incoming,sector,notes))
        c.executemany('INSERT INTO record_items(record_id,item_number,status,note) VALUES(?,?,?,?)',[(cur.lastrowid,*p) for p in parsed])
        rid=cur.lastrowid
    return jsonify(ok=True,id=rid),201

@app.get('/api/export')
@auth
def export():
    buffer=io.StringIO()
    writer=csv.writer(buffer,delimiter=';')
    writer.writerow(['ID','Registrado em UTC','Data do turno','Turno','Setor/Linha','Entrega','Recebimento','Criado por','Item','Verificação','Status','Pendência/Detalhes','Observações gerais'])
    with db() as c:
        rows=c.execute('''SELECT r.*,u.full_name author,i.item_number,i.status,i.note FROM records r JOIN users u ON u.id=r.created_by JOIN record_items i ON i.record_id=r.id ORDER BY r.id DESC,i.item_number''').fetchall()
    for r in rows:
        writer.writerow([r['id'],r['created_at'],r['shift_date'],r['shift'],r['sector'],r['outgoing'],r['incoming'],r['author'],r['item_number'],ITEMS[r['item_number']-1],{'ok':'Conforme','pending':'Pendente','na':'Não aplicável'}[r['status']],r['note'],r['notes']])
    return Response('\ufeff'+buffer.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="historico-passagem-turnos.csv"'})

@app.get('/api/users')
@admin
def list_users():
    with db() as c: rows=c.execute('SELECT id,username,full_name,role,active,created_at FROM users ORDER BY id').fetchall()
    return jsonify(users=[dict(r) for r in rows])

@app.post('/api/users')
@admin
def add_user():
    d=request.get_json(silent=True) or {}
    username=clean(d.get('username'),50)
    full_name=clean(d.get('full_name'))
    password=d.get('password','')
    role=d.get('role','user')
    if not username or not username.replace('_','').replace('.','').isalnum() or not full_name or not isinstance(password,str) or len(password)<10 or role not in ('user','admin'):
        return jsonify(error='Preencha nome, login (letras/números/._) e senha de pelo menos 10 caracteres.'),400
    try:
        with db() as c:
            cur=c.execute('INSERT INTO users(username,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',(username,full_name,generate_password_hash(password),role,now()))
        return jsonify(ok=True,id=cur.lastrowid),201
    except sqlite3.IntegrityError: return jsonify(error='Esse login já está cadastrado.'),409

@app.patch('/api/users/<int:uid>')
@admin
def edit_user(uid):
    d=request.get_json(silent=True) or {}
    with db() as c:
        existing=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not existing: return jsonify(error='Usuário não encontrado.'),404
        if uid==user()['id'] and 'active' in d and not d['active']:
            return jsonify(error='Você não pode desativar sua própria conta.'),400
        if uid==user()['id'] and d.get('role')=='user':
            return jsonify(error='Você não pode remover sua própria administração.'),400
        if 'active' in d:
            if type(d['active']) is not bool: return jsonify(error='Status inválido.'),400
            c.execute('UPDATE users SET active=? WHERE id=?',(int(d['active']),uid))
        if 'password' in d:
            if not isinstance(d['password'],str) or len(d['password'])<10: return jsonify(error='Senha deve ter no mínimo 10 caracteres.'),400
            c.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(d['password']),uid))
    return jsonify(ok=True)

@app.get('/health')
def health(): return jsonify(status='ok')


INITIAL_USERS = 16

def setup():
    """Cadastra até 16 contas administradoras e atualiza perfis existentes."""
    init_db()
    with db() as c:
        existing = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        updated = c.execute("UPDATE users SET role='admin' WHERE role!='admin'").rowcount
    if updated:
        print(f'{updated} conta(s) existente(s) promovida(s) a administrador. Histórico preservado.')
    if existing >= INITIAL_USERS:
        print(f'Já existem {existing} contas. Para adicionar outras, use o painel Usuários do administrador.')
        return
    missing = INITIAL_USERS - existing
    print(f'Existem {existing} contas; serão cadastradas mais {missing}, para totalizar {INITIAL_USERS}.')
    print('Todas as 16 contas terão perfil de administrador.')
    print('As senhas ficam ocultas e precisam ter no mínimo 10 caracteres.')
    from getpass import getpass
    creds=[]
    used=set()
    with db() as c:
        used = {row[0].lower() for row in c.execute('SELECT username FROM users')}
    for number in range(missing):
        role = 'admin'
        print(f'\nConta {existing+number+1}/{INITIAL_USERS}: Administrador')
        name=input('Nome completo: ').strip()
        username=input('Login: ').strip()
        password=getpass('Senha (mínimo 10 caracteres): ')
        if (not name or not username or not username.replace('_','').replace('.','').isalnum()
                or len(username)>50 or len(name)>100 or len(password)<10 or username.lower() in used):
            print('Dados inválidos ou login repetido. Nenhuma conta nova foi salva. Execute novamente.'); return
        used.add(username.lower())
        creds.append((username,name,generate_password_hash(password),role,now()))
    try:
        with db() as c:
            c.executemany('INSERT INTO users(username,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',creds)
        print(f'\n{missing} novas contas criadas! Total: {INITIAL_USERS}. Inicie com: python app.py')
    except sqlite3.IntegrityError:
        print('Erro: login duplicado. Nenhuma conta nova foi salva.')

def promote_all():
    """Transforma todos os usuários existentes em administradores sem apagar dados."""
    init_db()
    with db() as c:
        count = c.execute("UPDATE users SET role='admin' WHERE role!='admin'").rowcount
        total = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    print(f'{count} conta(s) promovida(s). Total de administradores: {total}.')

init_db()
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='setup': setup()
    elif len(sys.argv)>1 and sys.argv[1]=='promote-all': promote_all()
    else:
        if not os.environ.get('SECRET_KEY'): print('AVISO: defina SECRET_KEY no ambiente antes de publicar.')
        app.run(host='127.0.0.1',port=int(os.getenv('PORT',5000)),debug=False)