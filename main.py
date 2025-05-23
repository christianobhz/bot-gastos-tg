import os
import io
from dotenv import load_dotenv
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import pytz

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update
)
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from sheets import (
    init_sheets,
    add_lancamento,
    get_last_lancamentos,
    update_lancamento,
    delete_lancamento,
    get_all_lancamentos,
    get_all_user_ids,
    get_categories,
    add_category,
    delete_category,
    generate_report
)

load_dotenv()
TOKEN    = os.getenv("TELEGRAM_TOKEN")
TIMEZONE = os.getenv("TIMEZONE", "UTC")

# Teclado principal
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["➕ Novo", "✏️ Editar"],
     ["🗑️ Excluir", "📊 Relatório"],
     ["⚙️ Categorias", "❓ Ajuda"]],
    resize_keyboard=True
)

# Estados
TYPE, VALUE, CATEGORY, DESC, CONFIRM      = range(5)
SELECT, EVAL, ECAT, EDESC, ECONF         = range(5, 10)
DEL_SELECT, DEL_CONFIRM                   = range(10, 12)
R_TYPE                                   = 12
ADD_CAT_NAME, ADD_CAT_CONFIRM             = 13, 14
DEL_CAT_SELECT, DEL_CAT_CONFIRM           = 15, 16

# Scheduler
tz = pytz.timezone(TIMEZONE)
scheduler = AsyncIOScheduler(timezone=tz)
app = None

async def start_scheduler(application: Application):
    scheduler.start()

# --- Comandos básicos ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "👋 Olá! Bem-vindo ao Bot de Controle de Gastos.\n\n"
        "Use o menu abaixo para navegar:\n"
        "➕ Novo — registrar despesa/receita\n"
        "✏️ Editar — alterar lançamento\n"
        "🗑️ Excluir — remover lançamento\n"
        "📊 Relatório — gerar relatório\n"
        "⚙️ Categorias — gerenciar categorias\n"
        "❓ Ajuda — esta mensagem\n\n"
        "Em qualquer etapa digite /cancelar para voltar aqui."
    )
    await update.message.reply_text(texto, reply_markup=MAIN_KEYBOARD)

async def duvida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "🤖 *Ajuda Rápida* 🤖\n\n"
        "/start — menu principal\n"
        "/novo — registra despesa/receita\n"
        "/editar — edita um lançamento\n"
        "/excluir — exclui um lançamento\n"
        "/relatorio — gera relatório\n"
        "/categorias — lista categorias\n"
        "/addcategoria — adiciona categoria\n"
        "/delcategoria — remove categoria\n"
        "/duvida — esta ajuda\n"
        "/cancelar — cancela fluxo atual"
    )
    await update.message.reply_markdown(texto)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Fluxo cancelado.", reply_markup=MAIN_KEYBOARD)
    context.user_data.clear()
    return ConversationHandler.END

# --- /novo ---

async def novo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Despesa", callback_data="Despesa"),
        InlineKeyboardButton("Receita", callback_data="Receita")
    ]])
    await update.message.reply_text("Selecione o tipo:", reply_markup=kb)
    return TYPE

async def novo_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["tipo"] = q.data
    await q.edit_message_text(f"*Tipo*: {q.data}\n\nEnvie o *valor* (ex: 12.50):", parse_mode="Markdown")
    return VALUE

async def novo_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", ".")
    try:
        val = float(text); assert val > 0
    except:
        return await update.message.reply_text("Valor inválido. Digite um número maior que zero:")
    context.user_data["valor"] = val
    cats = get_categories()
    if not cats:
        return await update.message.reply_text("Nenhuma categoria disponível. Use /addcategoria.")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(c, callback_data=c)] for c in cats])
    await update.message.reply_text("Selecione a categoria:", reply_markup=kb)
    return CATEGORY

async def novo_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["categoria"] = q.data
    await q.edit_message_text(f"*Categoria*: {q.data}\n\nEnvie descrição (ou '-' para vazio):", parse_mode="Markdown")
    return DESC

async def novo_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    context.user_data["descricao"] = "" if desc == "-" else desc
    d = context.user_data
    resumo = (
        f"*Confirme lançamento:*\n"
        f"• Tipo: {d['tipo']}\n"
        f"• Valor: R$ {d['valor']:.2f}\n"
        f"• Categoria: {d['categoria']}\n"
        f"• Descrição: {d['descricao'] or '(vazia)'}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim", callback_data="yes"),
        InlineKeyboardButton("❌ Não", callback_data="no")
    ]])
    await update.message.reply_text(resumo, reply_markup=kb, parse_mode="Markdown")
    return CONFIRM

async def novo_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "yes":
        u = q.from_user; d = context.user_data
        new_id = add_lancamento(
            telegram_user_id=u.id,
            nome=u.full_name,
            tipo=d["tipo"],
            valor=d["valor"],
            categoria=d["categoria"],
            descricao=d["descricao"]
        )
        await q.edit_message_text(f"✅ ID *{new_id}* registrado.", parse_mode="Markdown")
    else:
        await q.edit_message_text("❌ Cancelado.")
    context.user_data.clear()
    return ConversationHandler.END

# --- /editar ---

async def editar_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lancs = get_last_lancamentos(uid)
    if not lancs:
        await update.message.reply_text("Nenhum lançamento para editar.")
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(
            f"{l['ID']} – {l['Timestamp']} – R$ {float(l['Valor']):.2f} – {l['Categoria']}",
            callback_data=f"edit_{l['ID']}"
        )] for l in reversed(lancs)
    ]
    await update.message.reply_text("Selecione um lançamento:", reply_markup=InlineKeyboardMarkup(buttons))
    return SELECT

async def editar_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lid = q.data.split("_", 1)[1]
    context.user_data["edit_id"] = lid
    orig = next((l for l in get_last_lancamentos(q.from_user.id, limit=1000) if l["ID"] == lid), {})
    context.user_data["orig"] = orig
    await q.edit_message_text(f"*ID {lid}* selecionado.\nValor atual: R$ {orig.get('Valor')}\nEnvie novo valor:", parse_mode="Markdown")
    return EVAL

async def editar_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", ".")
    try:
        val = float(text); assert val > 0
    except:
        return await update.message.reply_text("Valor inválido. Digite um número maior que zero:")
    context.user_data["new_valor"] = val
    cats = get_categories()
    if not cats:
        return await update.message.reply_text("Nenhuma categoria disponível.")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(c, callback_data=c)] for c in cats])
    await update.message.reply_text("Selecione nova categoria:", reply_markup=kb)
    return ECAT

async def editar_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["new_categoria"] = q.data
    await q.edit_message_text("Envie nova descrição (ou '-' para vazio):")
    return EDESC

async def editar_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    context.user_data["new_descricao"] = "" if desc == "-" else desc
    d, o = context.user_data, context.user_data["orig"]
    resumo = (
        f"*Confirme edição do ID {d['edit_id']}:*\n"
        f"• Valor: R$ {d['new_valor']:.2f} (antes R$ {o.get('Valor')})\n"
        f"• Categoria: {d['new_categoria']} (antes {o.get('Categoria')})\n"
        f"• Descrição: {d['new_descricao'] or '(vazia)'}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim", callback_data="yes"),
        InlineKeyboardButton("❌ Não", callback_data="no")
    ]])
    await update.message.reply_text(resumo, reply_markup=kb, parse_mode="Markdown")
    return ECONF

async def editar_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "yes":
        d = context.user_data
        update_lancamento(
            lanc_id=d["edit_id"],
            valor=d["new_valor"],
            categoria=d["new_categoria"],
            descricao=d["new_descricao"]
        )
        await q.edit_message_text(f"✅ ID *{d['edit_id']}* atualizado.", parse_mode="Markdown")
    else:
        await q.edit_message_text("❌ Cancelado.")
    context.user_data.clear()
    return ConversationHandler.END

# --- /excluir ---

async def excluir_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lancs = get_last_lancamentos(uid)
    if not lancs:
        await update.message.reply_text("Nenhum lançamento para excluir.")
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(
            f"{l['ID']} – {l['Timestamp']} – R$ {float(l['Valor']):.2f} – {l['Categoria']}",
            callback_data=f"del_{l['ID']}"
        )] for l in reversed(lancs)
    ]
    await update.message.reply_text("Selecione um lançamento:", reply_markup=InlineKeyboardMarkup(buttons))
    return DEL_SELECT

async def excluir_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lid = q.data.split("_", 1)[1]
    context.user_data["del_id"] = lid
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim", callback_data="yes"),
        InlineKeyboardButton("❌ Não", callback_data="no")
    ]])
    await q.edit_message_text(f"Excluir ID *{lid}*?", reply_markup=kb, parse_mode="Markdown")
    return DEL_CONFIRM

async def excluir_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lid = context.user_data["del_id"]
    if q.data == "yes":
        delete_lancamento(lid)
        await q.edit_message_text(f"✅ ID *{lid}* excluído.", parse_mode="Markdown")
    else:
        await q.edit_message_text("❌ Cancelado.")
    context.user_data.clear()
    return ConversationHandler.END

# --- /relatorio ---

async def relatorio_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Semanal", callback_data="Semanal"),
        InlineKeyboardButton("Quinzenal", callback_data="Quinzenal"),
        InlineKeyboardButton("Mensal", callback_data="Mensal")
    ]])
    await update.message.reply_text("Escolha o período:", reply_markup=kb)
    return R_TYPE

async def relatorio_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    period = q.data
    rpt = generate_report(period)
    texto = (
        f"🗓 *Relatório {period}*\n"
        f"Período: {rpt['start'].date()} a {rpt['end'].date()}\n"
        f"Total despesas: R$ {rpt['total_geral']:.2f}\n"
        f"🔻 *Total por Categoria:*\n"
    )
    for cat, val in rpt['totals_cat'].items():
        texto += f"  • {cat}: R$ {val:.2f}\n"
    await q.edit_message_text(texto, parse_mode="Markdown", reply_markup=None)
    return ConversationHandler.END

# --- categorias CRUD ---

async def lista_categorias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = get_categories()
    texto = ("Categorias:\n" + "\n".join(f"• {c}" for c in cats)) if cats else "Nenhuma categoria cadastrada."
    await update.message.reply_text(texto)

async def addcat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Envie o nome da nova categoria:")
    return ADD_CAT_NAME

async def addcat_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data["new_cat"] = name
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim", callback_data="yes"),
        InlineKeyboardButton("❌ Não", callback_data="no")
    ]])
    await update.message.reply_text(f"Deseja adicionar '{name}'?", reply_markup=kb)
    return ADD_CAT_CONFIRM

async def addcat_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    name = context.user_data["new_cat"]
    if q.data == "yes":
        ok = add_category(name)
        msg = f"✅ Categoria '{name}' adicionada." if ok else f"⚠️ Categoria '{name}' já existe."
    else:
        msg = "❌ Operação cancelada."
    await q.edit_message_text(msg)
    context.user_data.clear()
    return ConversationHandler.END

async def delcat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = get_categories()
    if not cats:
        await update.message.reply_text("Nenhuma categoria para excluir.")
        return ConversationHandler.END
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(c, callback_data=c)] for c in cats])
    await update.message.reply_text("Selecione a categoria para excluir:", reply_markup=kb)
    return DEL_CAT_SELECT

async def delcat_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    name = q.data
    context.user_data["del_cat"] = name
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim", callback_data="yes"),
        InlineKeyboardButton("❌ Não", callback_data="no")
    ]])
    await q.edit_message_reply_text(f"Excluir categoria '{name}'?", reply_markup=kb)
    return DEL_CAT_CONFIRM

async def delcat_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    name = context.user_data["del_cat"]
    if q.data == "yes":
        ok = delete_category(name)
        msg = f"✅ Categoria '{name}' excluída." if ok else f"⚠️ Categoria '{name}' não encontrada."
    else:
        msg = "❌ Operação cancelada."
    await q.edit_message_reply_text(msg)
    context.user_data.clear()
    return ConversationHandler.END

# --- relatórios agendados ---

async def send_report_to_user(bot, user_id, period):
    rpt = generate_report(period)
    texto = (
        f"🗓 *Relatório {period}*\n"
        f"Período: {rpt['start'].date()} a {rpt['end'].date()}\n"
        f"Total despesas: R$ {rpt['total_geral']:.2f}\n"
        f"🔻 *Total por Categoria:*\n"
    )
    for cat, val in rpt['totals_cat'].items():
        texto += f"  • {cat}: R$ {val:.2f}\n"
    await bot.send_message(chat_id=int(user_id), text=texto, parse_mode="Markdown")

async def broadcast_report(period):
    bot = app.bot
    for uid in get_all_user_ids():
        await send_report_to_user(bot, uid, period)

def main():
    global app
    init_sheets()

    # agenda relatórios
    scheduler.add_job(broadcast_report, CronTrigger(day_of_week="mon", hour=9, minute=0),
                      args=["Semanal"], id="rel_semanal")
    scheduler.add_job(broadcast_report, CronTrigger(day="1,15", hour=9, minute=0),
                      args=["Quinzenal"], id="rel_quinzenal")
    scheduler.add_job(broadcast_report, CronTrigger(day="last", hour=18, minute=0),
                      args=["Mensal"], id="rel_mensal")

    app = Application.builder()\
        .token(TOKEN)\
        .post_init(start_scheduler)\
        .build()

    # registra handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("duvida", duvida))
    app.add_handler(CommandHandler("cancelar", cancel))

    # Conversas
    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("novo", novo_start),
            MessageHandler(filters.Regex("^➕ Novo$"), novo_start)
        ],
        states={
            TYPE:     [CallbackQueryHandler(novo_type_chosen)],
            VALUE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, novo_value)],
            CATEGORY: [CallbackQueryHandler(novo_category_chosen)],
            DESC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, novo_desc)],
            CONFIRM:  [CallbackQueryHandler(novo_confirm)]
        },
        fallbacks=[CommandHandler("cancelar", cancel)]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("editar", editar_start),
            MessageHandler(filters.Regex("^✏️ Editar$"), editar_start)
        ],
        states={
            SELECT: [CallbackQueryHandler(editar_select, pattern="^edit_")],
            EVAL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, editar_value)],
            ECAT:   [CallbackQueryHandler(editar_category_chosen)],
            EDESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, editar_desc)],
            ECONF:  [CallbackQueryHandler(editar_confirm)]
        },
        fallbacks=[CommandHandler("cancelar", cancel)]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("excluir", excluir_start),
            MessageHandler(filters.Regex("^🗑️ Excluir$"), excluir_start)
        ],
        states={
            DEL_SELECT:  [CallbackQueryHandler(excluir_select, pattern="^del_")],
            DEL_CONFIRM: [CallbackQueryHandler(excluir_confirm)]
        },
        fallbacks=[CommandHandler("cancelar", cancel)]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("relatorio", relatorio_start),
            MessageHandler(filters.Regex("^📊 Relatório$"), relatorio_start)
        ],
        states={ R_TYPE: [CallbackQueryHandler(relatorio_chosen)] },
        fallbacks=[CommandHandler("cancelar", cancel)]
    ))

    # Categorias
    app.add_handler(CommandHandler("categorias", lista_categorias))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Categorias$"), lista_categorias))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addcategoria", addcat_start)],
        states={
            ADD_CAT_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, addcat_name)],
            ADD_CAT_CONFIRM: [CallbackQueryHandler(addcat_confirm)]
        },
        fallbacks=[CommandHandler("cancelar", cancel)]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("delcategoria", delcat_start)],
        states={
            DEL_CAT_SELECT:  [CallbackQueryHandler(delcat_select)],
            DEL_CAT_CONFIRM: [CallbackQueryHandler(delcat_confirm)]
        },
        fallbacks=[CommandHandler("cancelar", cancel)]
    ))

    print("Bot rodando… Ctrl+C para sair")
    app.run_polling()

if __name__ == "__main__":
    main()
