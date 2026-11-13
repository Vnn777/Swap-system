# Swap-system — Checklist de Passagem de Turno

Aplicação Flask com os 9 itens de passagem de turno da Regra Clara, login individual, painel de usuários, histórico compartilhado e exportação CSV. Preparado para **Render Free + PostgreSQL Neon Free**.

## Primeiro deploy (sem Codespaces)

1. Entre em https://console.neon.tech e crie um projeto gratuito chamado `swap-system` (PostgreSQL). Em **Connect**, copie a connection string do banco com SSL (`sslmode=require`). Ela contém uma senha: **não coloque no GitHub e não envie em chats**. Guarde também em gerenciador de senhas. Prefira conexão **Direct** para exportações com `pg_dump`.
2. Entre em https://dashboard.render.com e selecione **New > Blueprint**. Conecte `Vnn777/Swap-system` (branch `main`) e escolha o arquivo `render.yaml`. Se Blueprint não estiver disponível, crie **New > Web Service**, linguagem Python, plano Free, branch `main`, build `pip install -r requirements.txt` e start `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 app:app`.
3. Configure as variáveis **no Render** antes de implantar:
   - `DATABASE_URL`: string de conexão Neon PostgreSQL com SSL, **nunca** SQLite nem o PostgreSQL Free do Render.
   - `SECRET_KEY`: segredo aleatório longo; no Blueprint a chave é gerada automaticamente. No Web Service manual, gere um valor próprio e não mude após publicar.
   - `INITIAL_ADMIN_USERNAME`: login da primeira pessoa administradora.
   - `INITIAL_ADMIN_NAME`: nome completo dessa pessoa.
   - `INITIAL_ADMIN_PASSWORD`: senha temporária forte (mínimo 10 caracteres). **Não reutilize senhas pessoais**.
4. Faça deploy e verifique se o serviço está **Live**. Abra seu endereço HTTPS `https://<nome-do-servico>.onrender.com/login`, entre com o primeiro administrador e, em **Usuários**, adicione as outras **15 contas com perfil Administrador**. Cada pessoa deve ter uma senha única. O sistema permite adicionar mais contas no futuro.
5. Depois que o primeiro administrador existir e já tiver acessado o sistema, remova `INITIAL_ADMIN_PASSWORD` do ambiente do Render; não remova `SECRET_KEY` nem `DATABASE_URL`.
6. Teste: crie um checklist de exemplo, faça logout, entre novamente e confirme no Histórico. Teste novamente após um novo deploy. O banco deve manter os registros.

### Configuração sem Blueprint

| Campo | Valor |
| --- | --- |
| Tipo | Web Service |
| Repositório | `Vnn777/Swap-system` |
| Branch | `main` |
| Linguagem | Python 3 |
| Plano | Free |
| Build | `pip install -r requirements.txt` |
| Start | `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 app:app` |
| Health check | `/health` |

**Importante:** no Render a variável `DATABASE_URL` é obrigatória. Se estiver faltando, a inicialização será interrompida intencionalmente para não salvar dados em disco temporário. O app cria as tabelas automaticamente no PostgreSQL. Uma base SQLite antiga **não é importada automaticamente**.

## Backups criptografados automáticos

Incluído o workflow `.github/workflows/backup-neon.yml` para gerar **backup completo PostgreSQL (`pg_dump`) aos domingos às 03:00 UTC**, além da opção manual **Run workflow**. O arquivo é criptografado com AES-256-CBC e PBKDF2 antes de ser armazenado como artifact do GitHub por **30 dias** (ou menos, se a política do repositório limitar).

**Ativação obrigatória no GitHub:** abra **Settings > Secrets and variables > Actions > New repository secret**, e crie:

- `NEON_DATABASE_URL`: URL PostgreSQL **Direct** do Neon com SSL. É diferente da configuração `DATABASE_URL` no Render, mas pode apontar ao mesmo banco. Nunca coloque a URL no código nem em logs.
- `BACKUP_ENCRYPTION_PASSWORD`: frase de senha longa **única, idealmente 32+ caracteres**, guardada **fora do GitHub** também. Sem ela não será possível descriptografar o backup.

Em **Actions > Backup criptografado do Neon > Run workflow**, execute manualmente a primeira cópia e confira se o artifact `.dump.enc` foi gerado. A programação semanal depende das permissões e disponibilidade do GitHub Actions: veja os resultados do workflow regularmente. Agendamentos podem atrasar ou ser desativados por inatividade.

### Restaurar um backup (somente após testar em banco separado)

1. Faça **um backup novo** antes de qualquer restauração. Baixe o artifact do GitHub Actions e extraia `swap-system.dump.enc`.
2. Em computador com `openssl` e PostgreSQL client instalados, defina `BACKUP_PASSWORD` **localmente** (sem gravar no repositório) e execute:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in swap-system.dump.enc -out swap-system.dump \
  -pass env:BACKUP_PASSWORD
```

3. Crie um **banco vazio de teste** no Neon e configure `RESTORE_DATABASE_URL` para esse banco. **Nunca execute esses comandos no banco de produção sem revisão**, pois restaurações podem sobrescrever dados.

```bash
pg_restore --no-owner --no-acl --dbname="$RESTORE_DATABASE_URL" swap-system.dump
```

4. Verifique nesse banco de teste se as tabelas e registros foram recuperados; apague com segurança o arquivo `.dump` local, que contém dados não criptografados.

**Os backups do GitHub são limitados à retenção configurada.** Para reduzir o risco de perda total, baixe periodicamente cópias criptografadas e guarde em outro local seguro. O histórico de restauração do Neon Free é curto e **não substitui** os backups completos.

## Exportação CSV

Na interface, use **Histórico > Exportar Excel (CSV)** para uma cópia fácil dos checklists. Ela não inclui usuários, senhas ou estrutura do banco, então **não substitui** o backup completo do PostgreSQL. Trate os CSVs como documentos internos confidenciais.

## Uso local

```bash
pip install -r requirements.txt
python app.py setup
python app.py
```

Sem `DATABASE_URL`, o sistema usa SQLite local em `instance/turnos.db`; `python app.py setup` permite criar 16 contas administrativas. No Render usa PostgreSQL e a primeira conta nasce das variáveis `INITIAL_ADMIN_*`.

## Proteção de dados e limitações do plano Free

- Não publique credenciais no GitHub. A autenticação usa hash de senha e cookies `Secure` quando PostgreSQL está habilitado.
- Os 16 administradores podem gerenciar contas e consultar todo o histórico. Use senhas únicas e não compartilhe logins.
- Render Free hiberna após inatividade e o disco local é temporário; as informações salvas no **Neon externo** continuam persistentes nos reinícios, sujeito aos limites do plano Neon.
- Nenhum provedor garante risco zero. Para operação crítica da empresa, planeje monitoramento, backups externos, testes de restauração e eventual plano pago.