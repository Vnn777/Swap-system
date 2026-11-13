# Swap-system — Arquivo Digital de Checklists

Aplicação em Flask para passagem de turno da produção. **Uma única conta compartilhada**, botão **Criar checklist** e pastas automáticas por **mês/ano do salvamento** (horário de Fortaleza). Todos que entram na conta podem criar e consultar checklists. Cada checklist recebe ID, horário UTC do servidor (exibido em horário de Fortaleza), data do turno, responsáveis, setor, 9 verificações e observações.

## Antes de começar

**Não use a senha literal "Produção" em uma aplicação na internet:** ela é curta, comum e já foi escrita na conversa. Crie uma senha exclusiva com ao menos 12 caracteres. O usuário sugerido é `ADM Produção`, com espaço e acento.

## Hospedagem Render + Neon

1. Crie um banco PostgreSQL no Neon em https://console.neon.tech, plano Free. Em **Connect**, copie a URL com SSL. A conexão tem senha: nunca coloque no GitHub.
2. No Render https://dashboard.render.com, crie **New > Blueprint** com `Vnn777/Swap-system` na branch `main`. Ou Web Service com build `pip install -r requirements.txt` e start `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 app:app`.
3. Configure as variáveis **somente no painel do Render**:

| Variável | Valor |
|---|---|
| `DATABASE_URL` | URL PostgreSQL Neon com SSL (`sslmode=require`) |
| `SECRET_KEY` | Segredo aleatório persistente (Blueprint gera automaticamente) |
| `SHARED_LOGIN` | `ADM Produção` |
| `SHARED_PASSWORD` | Senha exclusiva com pelo menos 12 caracteres (não publicar) |

4. Faça deploy. Na primeira inicialização a conta é criada se não existir. Caso existam contas da versão anterior, elas são **desativadas**, mas os registros permanecem no banco e continuam acessíveis pelo arquivo. Nenhuma tabela nem checklist é excluído.
5. Entre em `/login` com `ADM Produção` e sua senha, crie um checklist de teste, salve, abra a pasta do mês e confirme a visualização. Saia e entre novamente para confirmar persistência.
6. **Retire `SHARED_PASSWORD` do Render depois de criar a conta**, para não manter a senha inicial desnecessariamente em configuração de inicialização. Não remova `DATABASE_URL` nem `SECRET_KEY`.

### Alterar a senha

A senha configurada em `SHARED_PASSWORD` é usada **somente ao criar a conta**; mudanças na variável não redefinem senhas automaticamente. Para redefinir, use um terminal confiável conectado ao mesmo banco e execute `python app.py reset-shared-password` com `SHARED_PASSWORD` definido para a nova senha. Faça um backup primeiro. A aplicação não disponibiliza redefinição pela interface.

### Migração sem perder os dados

- **Mantenha a mesma `DATABASE_URL`**. A migração desativa logins antigos e cria a nova conta; não remove usuários antigos porque os checklists ainda fazem referência a eles no banco.
- Se os checklists antigos estavam em SQLite local, eles **não serão automaticamente transferidos** ao Neon. Exige migração separada.
- A aplicação usa Neon quando `DATABASE_URL` está definido; no Render ela se recusa a iniciar sem o PostgreSQL para evitar dados no disco temporário.
- Se uma conta antiga tiver exatamente o login `ADM Produção`, será reutilizada (inclusive sua senha atual). Para redefini-la, siga o procedimento de troca de senha.

## Backup do Neon

O workflow `.github/workflows/backup-neon.yml` permanece disponível e pode executar um backup criptografado de PostgreSQL no GitHub Actions semanalmente. Para ativá-lo, configure em **GitHub > Settings > Secrets and variables > Actions**:

- `NEON_DATABASE_URL`: URL *Direct* do Neon com SSL (para `pg_dump`).
- `BACKUP_ENCRYPTION_PASSWORD`: senha forte e exclusiva de criptografia, mantida também fora do GitHub.

Acesse **Actions > Backup criptografado do Neon > Run workflow** para rodar o primeiro backup. Confira se o artefato criptografado foi gerado e **baixe uma cópia para outro local seguro**. O GitHub limita o tempo de retenção de artefatos, e agendamentos podem falhar ou ser adiados.

Para testar restauração, em máquina com PostgreSQL client e OpenSSL, baixe e extraia `swap-system.dump.enc`, defina `BACKUP_PASSWORD` localmente e rode:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in swap-system.dump.enc -out swap-system.dump -pass env:BACKUP_PASSWORD
pg_restore --no-owner --no-acl --dbname="$RESTORE_DATABASE_URL" swap-system.dump
```

**Restaure primeiro em um banco novo e separado**, nunca no banco em produção sem revisão. Confira os checklists recuperados e remova cópias de dump descriptografadas. O backup completo preserva usuários, hashes de senhas e checklists; o CSV é exportação de dados, não backup completo.

## Execução local (sem Codespaces)

```bash
pip install -r requirements.txt
# configure SHARED_PASSWORD com uma senha exclusiva de 12+ caracteres no ambiente
python app.py setup
python app.py
```

Sem `DATABASE_URL`, usa SQLite apenas para desenvolvimento em `instance/turnos.db`.

## Limitações e segurança

- Um login compartilhado **não identifica qual pessoa** realizou uma alteração. Preencha sempre os campos **responsável pela entrega/recebimento**. Para auditoria individual, seriam necessárias contas individuais.
- Quem conhece a senha consegue consultar todos os checklists. Compartilhe a senha apenas com pessoas autorizadas, preferencialmente por canal privado.
- O arquivo é organizado pelo **mês/ano em que o checklist foi salvo**, não pela data do turno preenchida.
- Os dados ficam no PostgreSQL Neon, não no disco temporário do Render. Nenhum plano gratuito oferece disponibilidade garantida ou risco zero de perda; mantenha backups externos.
