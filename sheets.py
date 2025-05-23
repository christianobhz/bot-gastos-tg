import os
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz
import calendar
from collections import defaultdict

# 1) Carrega variáveis de ambiente
load_dotenv()

# 2) Define escopos para Sheets e Drive
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# 3) Credenciais e cliente gspread
creds = Credentials.from_service_account_file(
    os.getenv("GOOGLE_CRED_PATH"),
    scopes=SCOPES
)
gc = gspread.authorize(creds)

# 4) Abre a planilha pelo ID
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
sh = gc.open_by_key(SPREADSHEET_ID)

# Lista de categorias padrão, em ordem alfabética
DEFAULT_CATEGORIES = [
    "Alimentação",
    "Cuidados Pessoais",
    "Dívidas/Empréstimos",
    "Educação",
    "Farmácia",
    "Impostos",
    "Lazer",
    "Mercado",
    "Moradia",
    "Outros",
    "Pet",
    "Presentes/Doações",
    "Saúde",
    "Transporte",
    "Vestuário"
]

# 5) Nomes das abas e cabeçalhos
SHEETS = {
    "Lançamentos": ["ID", "Timestamp", "Telegram User ID", "Nome", "Tipo", "Valor", "Categoria", "Descrição"],
    "Config":      ["Último ID"],
    "Categorias":  ["Categoria"]
}

def init_sheets():
    """
    Garante que cada aba exista e, se estiver vazia, escreve o cabeçalho.
    Para 'Categorias', popula DEFAULT_CATEGORIES na primeira criação.
    """
    for name, header in SHEETS.items():
        try:
            ws = sh.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=name, rows="100", cols=str(len(header)))
            print(f"Aba '{name}' criada.")
        # se não há cabeçalho, insere
        if not ws.row_values(1):
            ws.insert_row(header, index=1)
            print(f"Cabeçalho da aba '{name}' inserido.")
        # se for aba Categorias e só tiver header, popula defaults
        if name == "Categorias":
            vals = ws.get_all_values()
            if len(vals) == 1:  # apenas header
                for cat in DEFAULT_CATEGORIES:
                    ws.append_row([cat])
                print("Categorias padrão inseridas.")
    print("Inicialização das planilhas concluída.")

def get_next_id():
    """Lê o último ID em Config e retorna o próximo."""
    cfg = sh.worksheet("Config")
    vals = cfg.col_values(1)
    last = int(vals[1]) if len(vals) > 1 and vals[1].isdigit() else 0
    return last + 1

def update_last_id(new_id):
    """Escreve o novo último ID na célula A2 da aba Config."""
    cfg = sh.worksheet("Config")
    if len(cfg.get_all_values()) < 2:
        cfg.insert_row([str(new_id)], index=2)
    else:
        cfg.update_cell(2, 1, str(new_id))

def add_lancamento(telegram_user_id, nome, tipo, valor, categoria, descricao):
    """Insere nova linha em 'Lançamentos' e atualiza Config. Retorna o ID gerado."""
    new_id = get_next_id()
    tz = pytz.timezone(os.getenv("TIMEZONE", "UTC"))
    ts = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    row = [
        new_id,
        ts,
        telegram_user_id,
        nome or "",
        tipo,
        f"{valor:.2f}",
        categoria,
        descricao or ""
    ]
    sh.worksheet("Lançamentos").append_row(row)
    update_last_id(new_id)
    return new_id

def get_last_lancamentos(telegram_user_id, limit=10):
    """Retorna os últimos `limit` lançamentos do usuário."""
    ws = sh.worksheet("Lançamentos")
    rows = ws.get_all_values()[1:]
    results = []
    for row in rows:
        if len(row) >= 3 and row[2] == str(telegram_user_id):
            results.append({
                "ID": row[0],
                "Timestamp": row[1],
                "Telegram User ID": row[2],
                "Nome": row[3],
                "Tipo": row[4],
                "Valor": row[5],
                "Categoria": row[6],
                "Descrição": row[7] if len(row) > 7 else ""
            })
    return results[-limit:]

def update_lancamento(lanc_id, valor=None, categoria=None, descricao=None):
    """Atualiza o lançamento de ID=lanc_id nos campos fornecidos."""
    ws = sh.worksheet("Lançamentos")
    ids = ws.col_values(1)
    try:
        idx = ids.index(str(lanc_id)) + 1
    except ValueError:
        raise Exception(f"ID {lanc_id} não encontrado.")
    if valor is not None:
        ws.update_cell(idx, 6, f"{valor:.2f}")
    if categoria is not None:
        ws.update_cell(idx, 7, categoria)
    if descricao is not None:
        ws.update_cell(idx, 8, descricao)

def delete_lancamento(lanc_id):
    """Remove o lançamento de ID=lanc_id."""
    ws = sh.worksheet("Lançamentos")
    ids = ws.col_values(1)
    try:
        idx = ids.index(str(lanc_id)) + 1
    except ValueError:
        raise Exception(f"ID {lanc_id} não encontrado.")
    ws.delete_rows(idx)

def get_all_lancamentos(telegram_user_id):
    """Retorna todos os lançamentos de um usuário como lista de dicts."""
    ws = sh.worksheet("Lançamentos")
    rows = ws.get_all_values()[1:]
    out = []
    for row in rows:
        if len(row) >= 3 and row[2] == str(telegram_user_id):
            out.append({
                "ID": row[0],
                "Timestamp": row[1],
                "Telegram User ID": row[2],
                "Nome": row[3],
                "Tipo": row[4],
                "Valor": float(row[5].replace(",", ".")),
                "Categoria": row[6],
                "Descrição": row[7] if len(row) > 7 else ""
            })
    return out

def get_all_user_ids():
    """Retorna set de todos os Telegram User IDs na aba 'Lançamentos'."""
    ws = sh.worksheet("Lançamentos")
    vals = ws.col_values(3)[1:]
    return set(vals)

def get_categories():
    """Retorna lista das categorias cadastradas."""
    ws = sh.worksheet("Categorias")
    vals = ws.col_values(1)[1:]
    cats = []
    for v in vals:
        v = v.strip()
        if v and v not in cats:
            cats.append(v)
    return cats

def add_category(name):
    """Adiciona categoria se não existir; retorna True/False."""
    ws = sh.worksheet("Categorias")
    cats = get_categories()
    if name in cats:
        return False
    ws.append_row([name])
    return True

def delete_category(name):
    """Exclui categoria; retorna True se removeu, False se não achou."""
    ws = sh.worksheet("Categorias")
    vals = ws.col_values(1)
    try:
        idx = vals.index(name) + 1
    except ValueError:
        return False
    ws.delete_rows(idx)
    return True

def _get_period_range(period):
    """Auxiliar para gerar intervalo de datas."""
    tz = pytz.timezone(os.getenv("TIMEZONE", "UTC"))
    now = datetime.now(tz)
    if period == "Semanal":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
        end   = start + timedelta(days=7)
    elif period == "Quinzenal":
        if now.day <= 15:
            start = now.replace(day=1, hour=0, minute=0, second=0)
            end   = now.replace(day=15, hour=23, minute=59, second=59)
        else:
            start = now.replace(day=16, hour=0, minute=0, second=0)
            last  = calendar.monthrange(now.year, now.month)[1]
            end   = now.replace(day=last, hour=23, minute=59, second=59)
    elif period == "Mensal":
        start = now.replace(day=1, hour=0, minute=0, second=0)
        last  = calendar.monthrange(now.year, now.month)[1]
        end   = now.replace(day=last, hour=23, minute=59, second=59)
    else:
        raise ValueError("Período inválido")
    return start, end

def generate_report(period):
    """
    Gera relatório para 'Semanal', 'Quinzenal' ou 'Mensal'.
    Retorna dict com totals_cat, totals_user, total_geral, start e end.
    """
    start, end = _get_period_range(period)
    tz = pytz.timezone(os.getenv("TIMEZONE", "UTC"))
    rows = sh.worksheet("Lançamentos").get_all_values()[1:]
    totals_cat = defaultdict(float)
    totals_user = defaultdict(float)
    for row in rows:
        try:
            ts = tz.localize(datetime.strptime(row[1], "%Y-%m-%d %H:%M"))
        except:
            continue
        if not (start <= ts <= end):
            continue
        if row[4] != "Despesa":
            continue
        val = float(row[5].replace(",", "."))
        cat = row[6]
        user = row[3] or row[2]
        totals_cat[cat] += val
        totals_user[user] += val
    return {
        "totals_cat": dict(totals_cat),
        "totals_user": dict(totals_user),
        "total_geral": sum(totals_cat.values()),
        "start": start,
        "end": end
    }