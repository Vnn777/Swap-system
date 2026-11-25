import csv
import base64
import binascii
import io
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from PIL import Image, UnidentifiedImageError

BASE = Path(__file__).resolve().parent
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
if os.getenv('RENDER') and not DATABASE_URL:
    raise RuntimeError('DATABASE_URL obrigatoria no Render. Configure Neon PostgreSQL.')
DB = Path(os.getenv('DATABASE_PATH', str(BASE / 'instance' / 'turnos.db')))
if not DATABASE_URL:
    DB.parent.mkdir(parents=True, exist_ok=True)
if DATABASE_URL and not os.getenv('SECRET_KEY'):
    raise RuntimeError('SECRET_KEY obrigatoria em producao.')
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=bool(DATABASE_URL) or os.getenv('COOKIE_SECURE', '0') == '1', PERMANENT_SESSION_LIFETIME=timedelta(hours=10), MAX_CONTENT_LENGTH=8000000)
ITEMS = ['Organização e Limpeza','Insumos disponíveis','Manipulado e acabado liberados','Reatores cheios, quando não possível, kanban disponível','Passagem de turno líder a líder de linha','Apontamento nas linhas atualizado','IBCs disponíveis para envase','Paletes disponíveis para produção','Paletes quebrados no descarte']
STATUSES = {'ok', 'pending', 'na'}
MAX_PHOTOS_PER_ITEM = 2
MAX_PHOTOS_PER_RECORD = 10
MAX_PHOTO_BYTES = 600_000

class PgRow(dict):
    """Suporta acesso por chave e indice (compatibilidade sqlite3.Row)."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

class PgCursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount
    def fetchone(self):
        row = self.cursor.fetchone()
        return PgRow(row) if row is not None else None
    def fetchall(self):
        return [PgRow(row) for row in self.cursor.fetchall()]

class PgConnection:
    def __init__(self):
        self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
    def __enter__(self):
        self.conn.__enter__()
        return self
    def __exit__(self, exc_type, exc_value, traceback):
        return self.conn.__exit__(exc_type, exc_value, traceback)
    def execute(self, sql, params=()):
        statement = sql.replace('?', '%s')
        is_insert = statement.lstrip().upper().startswith('INSERT INTO USERS') or statement.lstrip().upper().startswith('INSERT INTO RECORDS(')
        if is_insert and 'RETURNING' not in statement.upper():
            statement += ' RETURNING id'
        cursor = self.conn.execute(statement, params)
        if is_insert:
            row = cursor.fetchone()
            return PgCursor(cursor, row['id'] if row else None)
        return PgCursor(cursor)
    def executemany(self, sql, params):
        cursor = self.conn.cursor()
        cursor.executemany(sql.replace('?', '%s'), params)
        return PgCursor(cursor)

def db():
    if DATABASE_URL:
        if psycopg is None:
            raise RuntimeError('Instale psycopg[binary].')
        return PgConnection()
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    return conn

def init_db():
    if DATABASE_URL:
        with db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS users(
                id BIGSERIAL PRIMARY KEY, username TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')),
                active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)""")
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_idx ON users (LOWER(username))')
            c.execute("""CREATE TABLE IF NOT EXISTS records(
                id BIGSERIAL PRIMARY KEY, created_by BIGINT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL, shift_date TEXT NOT NULL, shift TEXT NOT NULL,
                outgoing TEXT NOT NULL, incoming TEXT NOT NULL, sector TEXT NOT NULL,
                notes TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS record_items(
                record_id BIGINT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                item_number INTEGER NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL,
                PRIMARY KEY(record_id,item_number))""")
            c.execute("""CREATE TABLE IF NOT EXISTS record_photos(
                id BIGSERIAL PRIMARY KEY,
                record_id BIGINT NOT NULL,
                item_number INTEGER NOT NULL,
                mime_type TEXT NOT NULL CHECK(mime_type='image/jpeg'),
                content BYTEA NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(record_id,item_number) REFERENCES record_items(record_id,item_number) ON DELETE CASCADE
            )""")
            c.execute('CREATE INDEX IF NOT EXISTS record_photos_record_idx ON record_photos(record_id)')
            c.execute("ALTER TABLE record_items ADD COLUMN IF NOT EXISTS lines TEXT NOT NULL DEFAULT '[]'")
    else:
        with db() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL COLLATE NOCASE UNIQUE,full_name TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','user')),active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,shift_date TEXT NOT NULL,shift TEXT NOT NULL,outgoing TEXT NOT NULL,incoming TEXT NOT NULL,sector TEXT NOT NULL,notes TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS record_items(record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,item_number INTEGER NOT NULL,status TEXT NOT NULL,note TEXT NOT NULL,PRIMARY KEY(record_id,item_number));
            CREATE TABLE IF NOT EXISTS record_photos(id INTEGER PRIMARY KEY,record_id INTEGER NOT NULL,item_number INTEGER NOT NULL,mime_type TEXT NOT NULL,content BLOB NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(record_id,item_number) REFERENCES record_items(record_id,item_number) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS record_photos_record_idx ON record_photos(record_id);""")
            if not any(row[1] == "lines" for row in c.execute("PRAGMA table_info(record_items)").fetchall()):
                c.execute("ALTER TABLE record_items ADD COLUMN lines TEXT NOT NULL DEFAULT '[]'")

def bootstrap_shared():
    """Cria uma conta compartilhada e bloqueia contas antigas sem apagar checklists."""
    login = os.getenv('SHARED_LOGIN', 'ADM Produção').strip()
    password = os.getenv('SHARED_PASSWORD', '')
    if not login or len(login) > 50:
        raise RuntimeError('SHARED_LOGIN invalido.')
    with db() as c:
        current = c.execute('SELECT id FROM users WHERE LOWER(username)=LOWER(?)', (login,)).fetchone()
        if current is None:
            if not password:
                app.logger.warning('Configure SHARED_PASSWORD para criar a conta compartilhada.')
                return
            if len(password) < 12:
                raise RuntimeError('SHARED_PASSWORD deve ter pelo menos 12 caracteres.')
            current = c.execute('INSERT INTO users(username,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                                (login,'ADM Produção',generate_password_hash(password),'admin',now()))
            shared_id = current.lastrowid
        else:
            shared_id = current['id']
        c.execute("UPDATE users SET active=0 WHERE id<>? AND active<>0", (shared_id,))
        c.execute("UPDATE users SET active=1, role='admin' WHERE id=?", (shared_id,))

def reset_shared_password():
    """Redefine a senha sob comando explícito; não reinicia senhas em cada deploy."""
    password = os.getenv('SHARED_PASSWORD', '')
    if len(password) < 12:
        raise RuntimeError('Defina SHARED_PASSWORD com 12 caracteres ou mais.')
    login = os.getenv('SHARED_LOGIN', 'ADM Produção').strip()
    with db() as c:
        row = c.execute('SELECT id FROM users WHERE LOWER(username)=LOWER(?)', (login,)).fetchone()
        if not row:
            raise RuntimeError('Conta compartilhada não encontrada.')
        c.execute('UPDATE users SET password_hash=? WHERE id=?',
                  (generate_password_hash(password),row['id']))
    print('Senha compartilhada atualizada.')

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def clean(v, n=100): return v.strip() if isinstance(v,str) and len(v.strip()) <= n else ''
def user():
    uid=session.get('uid')
    if not uid: return None
    with db() as c: return c.execute('SELECT id,username,full_name,role FROM users WHERE id=? AND active=1 AND LOWER(username)=LOWER(?)',(uid,os.getenv('SHARED_LOGIN','ADM Produção'))).fetchone()

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
    with db() as c: u=c.execute('SELECT * FROM users WHERE LOWER(username)=LOWER(?) AND LOWER(username)=LOWER(?) AND active=1',(username,os.getenv('SHARED_LOGIN','ADM Produção'))).fetchone()
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
        rows=c.execute('''SELECT r.*,u.full_name AS author,(SELECT COUNT(*) FROM record_items i WHERE i.record_id=r.id AND i.status='pending') AS pending_count FROM records r JOIN users u ON u.id=r.created_by ORDER BY r.id DESC''').fetchall()
    return jsonify(records=[dict(r) for r in rows])

@app.get('/api/records/<int:rid>')
@auth
def record_detail(rid):
    with db() as c:
        r=c.execute('SELECT r.*,u.full_name AS author FROM records r JOIN users u ON u.id=r.created_by WHERE r.id=?',(rid,)).fetchone()
        if not r: return jsonify(error='Registro não encontrado.'),404
        items=c.execute('SELECT item_number,status,note,lines FROM record_items WHERE record_id=? ORDER BY item_number',(rid,)).fetchall()
        photos=c.execute('SELECT id,item_number FROM record_photos WHERE record_id=? ORDER BY id',(rid,)).fetchall()
    by_item = {}
    for p in photos:
        by_item.setdefault(p['item_number'],[]).append({'id':p['id'],'url':url_for('photo_file',rid=rid,pid=p['id'])})
    return jsonify(record=dict(r),items=[{**dict(i),'lines':json.loads(i['lines'] or '[]'),'photos':by_item.get(i['item_number'],[])} for i in items])

@app.get('/api/records/<int:rid>/photos/<int:pid>')
@auth
def photo_file(rid,pid):
    with db() as c:
        p=c.execute('SELECT mime_type,content FROM record_photos WHERE record_id=? AND id=?',(rid,pid)).fetchone()
    if p is None:
        abort(404)
    content=p['content']
    if isinstance(content,memoryview):
        content=content.tobytes()
    return Response(content, mimetype=p['mime_type'], headers={
        'Content-Disposition':'inline; filename="evidencia.jpg"',
        'X-Content-Type-Options':'nosniff',
        'Cache-Control':'no-store, private'
    })

@app.post('/api/records')
@auth
def save_record():
    data=request.get_json(silent=True) or {}
    date=clean(data.get('date'),10)
    shift=clean(data.get('shift'),30)
    outgoing=clean(data.get('outgoing'))
    incoming=clean(data.get('incoming'))
    sector='Linhas selecionadas'
    notes=clean(data.get('notes'),3000)
    items=data.get('items')
    try: datetime.strptime(date,'%Y-%m-%d')
    except (ValueError,TypeError): return jsonify(error='Data inválida.'),400
    if shift not in ('Turno A','Turno B','Turno C','Turno D') or not all((outgoing,incoming)) or not isinstance(items,list) or len(items)!=9:
        return jsonify(error='Preencha todos os campos e avalie os 9 itens.'),400
    parsed=[]
    photo_rows=[]
    for i,entry in enumerate(items,1):
        if not isinstance(entry,dict) or entry.get('status') not in STATUSES:
            return jsonify(error=f'Avalie o item {i}.'),400
        lines=entry.get('lines',[])
        if (not isinstance(lines,list) or not lines or len(lines)>16 or
            any(type(line) is not int or not 1<=line<=16 for line in lines) or
            len(set(lines))!=len(lines)):
            return jsonify(error=f'Selecione as linhas de 1 a 16 no item {i}.'),400
        note=clean(entry.get('note',''),500)
        if entry['status']=='pending' and not note:
            return jsonify(error=f'Descreva a pendência do item {i}.'),400
        photos=entry.get('photos',[])
        if not isinstance(photos,list) or len(photos)>MAX_PHOTOS_PER_ITEM:
            return jsonify(error=f'No máximo {MAX_PHOTOS_PER_ITEM} fotos no item {i}.'),400
        for photo in photos:
            if not isinstance(photo,str) or not photo.startswith('data:image/jpeg;base64,'):
                return jsonify(error=f'Formato de foto inválido no item {i}.'),400
            try:
                raw=base64.b64decode(photo.split(',',1)[1],validate=True)
                if len(raw)>MAX_PHOTO_BYTES or len(raw)<100:
                    return jsonify(error=f'Foto do item {i} excede o limite de 600 KB.'),400
                with Image.open(io.BytesIO(raw)) as img:
                    if img.format!='JPEG' or img.width>2000 or img.height>2000:
                        return jsonify(error=f'Foto inválida no item {i}.'),400
                    img.verify()
            except (ValueError, binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError):
                return jsonify(error=f'Não foi possível validar a foto do item {i}.'),400
            photo_rows.append((i,'image/jpeg',raw,now()))
        if len(photo_rows)>MAX_PHOTOS_PER_RECORD:
            return jsonify(error='Limite de 10 fotos por checklist.'),400
        parsed.append((i,entry['status'],note,json.dumps(sorted(lines))))
    with db() as c:
        cur=c.execute('INSERT INTO records(created_by,created_at,shift_date,shift,outgoing,incoming,sector,notes) VALUES(?,?,?,?,?,?,?,?)',(user()['id'],now(),date,shift,outgoing,incoming,sector,notes))
        c.executemany('INSERT INTO record_items(record_id,item_number,status,note,lines) VALUES(?,?,?,?,?)',[(cur.lastrowid,*p) for p in parsed])
        if photo_rows:
            c.executemany('INSERT INTO record_photos(record_id,item_number,mime_type,content,created_at) VALUES(?,?,?,?,?)',
                          [(cur.lastrowid,*p) for p in photo_rows])
        rid=cur.lastrowid
    return jsonify(ok=True,id=rid),201

@app.get('/api/export')
@auth
def export():
    buffer=io.StringIO()
    writer=csv.writer(buffer,delimiter=';')
    writer.writerow(['ID','Registrado em UTC','Data do turno','Turno','Linhas avaliadas','Responsável pela Vistoria da Linha','Responsáveis ou Líder da Linha','Criado por','Item','Verificação','Status','Pendência/Detalhes','Observações gerais'])
    with db() as c:
        rows=c.execute('''SELECT r.*,u.full_name author,i.item_number,i.status,i.note,i.lines FROM records r JOIN users u ON u.id=r.created_by JOIN record_items i ON i.record_id=r.id ORDER BY r.id DESC,i.item_number''').fetchall()
    for r in rows:
        writer.writerow([r['id'],r['created_at'],r['shift_date'],r['shift'],', '.join('Linha '+str(n) for n in json.loads(r['lines'] or '[]')) or '(registro antigo sem seleção)',r['outgoing'],r['incoming'],r['author'],r['item_number'],ITEMS[r['item_number']-1],{'ok':'Conforme','pending':'Pendente','na':'Não aplicável'}[r['status']],r['note'],r['notes']])
    return Response('\ufeff'+buffer.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="historico-passagem-turnos.csv"'})

@app.get('/health')
def health():
    try:
        with db() as c:
            c.execute('SELECT 1').fetchone()
        return jsonify(status='ok')
    except Exception:
        app.logger.exception('Falha de banco de dados no health check')
        return jsonify(status='unavailable'),503


def setup():
    init_db()
    bootstrap_shared()
    with db() as c:
        row = c.execute('SELECT username,active FROM users WHERE LOWER(username)=LOWER(?)',
                        (os.getenv('SHARED_LOGIN','ADM Produção').strip(),)).fetchone()
    if not row:
        print('Configure SHARED_PASSWORD antes de executar setup.')
    else:
        print('Conta compartilhada pronta:', row['username'])

init_db()
bootstrap_shared()
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='setup': setup()
    elif len(sys.argv)>1 and sys.argv[1]=='reset-shared-password': reset_shared_password()
    else:
        if not os.environ.get('SECRET_KEY'): print('AVISO: defina SECRET_KEY no ambiente antes de publicar.')
        app.run(host='0.0.0.0',port=int(os.getenv('PORT',5000)),debug=False)