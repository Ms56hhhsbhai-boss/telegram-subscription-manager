import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from dotenv import load_dotenv

from database import Database

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO)
db = Database(DATABASE_URL)
dp = Dispatcher()


class AddStock(StatesGroup):
    details = State()
    supplier = State()
    cost = State()


class SellItem(StatesGroup):
    item_id = State()
    price = State()
    customer = State()


class AddExpense(StatesGroup):
    description = State()
    amount = State()


def money(value):
    return f"₹{Decimal(str(value or 0)):,.2f}"


def parse_amount(value):
    try:
        amount = Decimal(value.strip().replace(",", ""))
        if not amount.is_finite() or amount <= 0:
            return None
        return amount
    except (InvalidOperation, AttributeError):
        return None


async def admin_only(message: Message) -> bool:
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        await message.answer("⛔ This is a private admin bot.")
        return False
    return True


@dp.message(Command("start"))
async def start(message: Message):
    if not await admin_only(message):
        return
    await message.answer(
        "Welcome to your Email Account Sales Manager.\n\n"
        "/addstock — save a full account details message\n"
        "/stock — view available account records\n"
        "/sell — record a sale\n"
        "/expense — record a business expense\n"
        "/report — daily or monthly report\n"
        "/history — recent sales\n"
        "/customers — customer history\n"
        "/cancel — cancel the current operation\n"
        "/help — show commands"
    )


@dp.message(Command("help"))
async def help_cmd(message: Message):
    if await admin_only(message):
        await start(message)


@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    await state.clear()
    await message.answer("Operation cancelled.")


@dp.message(Command("addstock"))
async def addstock(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    await state.clear()
    await state.set_state(AddStock.details)
    await message.answer("Paste the complete account details message (up to 3000 characters). It can contain multiple lines:")


@dp.message(AddStock.details)
async def addstock_details(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    details = (message.text or "").strip()
    if not details or len(details) > 3000:
        await message.answer("Please send a non-empty text message up to 3000 characters.")
        return
    await state.update_data(details=details)
    await state.set_state(AddStock.supplier)
    await message.answer("Who did you buy this account from? Enter the seller's name/reference:")


@dp.message(AddStock.supplier)
async def addstock_supplier(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    supplier = (message.text or "").strip()
    if not supplier or len(supplier) > 120:
        await message.answer("Enter a seller name/reference up to 120 characters.")
        return
    await state.update_data(supplier=supplier)
    await state.set_state(AddStock.cost)
    await message.answer("Enter the purchase cost of this account (e.g. 299.50):")


@dp.message(AddStock.cost)
async def addstock_cost(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer("Enter a valid positive amount.")
        return
    data = await state.get_data()
    try:
        item_id = db.add_inventory(data["details"], data["supplier"], amount)
    except Exception:
        logging.exception("Could not add account record")
        await message.answer("Could not add this account record. It may already exist. Try /addstock again.")
        await state.clear()
        return
    await state.clear()
    await message.answer(
        f"✅ ACCOUNT ADDED\\nID: #{item_id}\\nDetails saved as a message.\\n"
        f"Bought from: {data['supplier']}\\nPurchase cost: {money(amount)}"
    )


@dp.message(Command("stock"))
async def stock(message: Message):
    if not await admin_only(message):
        return
    items = db.available_inventory()
    if not items:
        await message.answer("Your inventory is empty.")
        return
    lines = ["📦 AVAILABLE INVENTORY"]
    for item in items[:60]:
        lines.append(f"#{item['id']} · {item['name'][:180].replace(chr(10), ' | ')} · From: {item['supplier']} · Cost {money(item['cost'])}")
    if len(items) > 60:
        lines.append(f"...and {len(items)-60} more. Showing first 60.")
    await message.answer("\n".join(lines))


@dp.message(Command("sell"))
async def sell(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    await state.clear()
    items = db.available_inventory()
    if not items:
        await message.answer("No available stock. Add inventory with /addstock.")
        return
    lines = ["Which inventory ID are you selling?"]
    lines += [f"#{x['id']} · {x['name'][:180].replace(chr(10), ' | ')} · From: {x['supplier']} · Cost {money(x['cost'])}" for x in items[:50]]
    await state.set_state(SellItem.item_id)
    await message.answer("\n".join(lines))


@dp.message(SellItem.item_id)
async def sell_id(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    try:
        item_id = int((message.text or "").strip().lstrip("#"))
    except ValueError:
        await message.answer("Enter a valid inventory ID.")
        return
    item = db.get_available_item(item_id)
    if not item:
        await message.answer("That ID is not available. Check /stock or /cancel.")
        return
    await state.update_data(item_id=item_id)
    await state.set_state(SellItem.price)
    await message.answer(f"Selected account #{item_id}: {item['name'][:500]}\\nBought from: {item['supplier']}\\nEnter selling price:")


@dp.message(SellItem.price)
async def sell_price(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer("Enter a valid positive selling price.")
        return
    await state.update_data(price=str(amount))
    await state.set_state(SellItem.customer)
    await message.answer("Enter customer name or reference (or type - to skip):")


@dp.message(SellItem.customer)
async def sell_customer(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    data = await state.get_data()
    customer = (message.text or "").strip()
    if customer == "-":
        customer = ""
    if len(customer) > 120:
        await message.answer("Keep the customer name/reference under 120 characters.")
        return
    result = db.record_sale(data["item_id"], Decimal(data["price"]), customer)
    await state.clear()
    if not result:
        await message.answer("❌ Sale could not be recorded. The item may already have been sold.")
        return
    await message.answer(
        "✅ SALE RECORDED\n"
        f"Account ID: #{result['item_id']}\n"
        f"Bought from: {result['supplier']}\n"
        f"Sold to: {result['customer'] or 'Not specified'}\n"
        f"Sale: {money(result['price'])}\n"
        f"Cost: {money(result['cost'])}\n"
        f"Gross profit: {money(result['profit'])}"
    )


@dp.message(Command("expense"))
async def expense(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    await state.clear()
    await state.set_state(AddExpense.description)
    await message.answer("Enter expense description:")


@dp.message(AddExpense.description)
async def expense_desc(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    desc = (message.text or "").strip()
    if not desc or len(desc) > 160:
        await message.answer("Enter a description up to 160 characters.")
        return
    await state.update_data(description=desc)
    await state.set_state(AddExpense.amount)
    await message.answer("Enter expense amount:")


@dp.message(AddExpense.amount)
async def expense_amount(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer("Enter a valid positive amount.")
        return
    data = await state.get_data()
    db.add_expense(data["description"], amount)
    await state.clear()
    await message.answer(f"✅ Expense saved: {data['description']} · {money(amount)}")


@dp.message(Command("report"))
async def report(message: Message):
    if not await admin_only(message):
        return
    args = (message.text or "").split(maxsplit=1)
    period = args[1].lower() if len(args) > 1 else "today"
    if period in ("today", "daily"):
        start = date.today().isoformat()
        label = f"Today ({start})"
    elif period in ("month", "monthly"):
        start = date.today().replace(day=1).isoformat()
        label = date.today().strftime("%B %Y")
    else:
        await message.answer("Usage: /report [today|month]")
        return
    r = db.report(start)
    await message.answer(
        f"📊 {label} REPORT\n\n"
        f"Sales: {r['count']}\n"
        f"Revenue: {money(r['revenue'])}\n"
        f"Cost of sold stock: {money(r['cost'])}\n"
        f"Gross profit: {money(r['gross_profit'])}\n"
        f"Expenses: {money(r['expenses'])}\n"
        f"Net profit: {money(r['net_profit'])}\n"
        f"Units currently in stock: {r['stock']}"
    )


@dp.message(Command("history"))
async def history(message: Message):
    if not await admin_only(message):
        return
    rows = db.sales_history(20)
    if not rows:
        await message.answer("No sales recorded yet.")
        return
    lines = ["🧾 RECENT SALES"]
    for x in rows:
        lines.append(
            f"#{x['id']} · {x['name']}\\nBought from: {x['supplier']} · Sold to: {x['customer'] or 'Not specified'}\\n"
            f"Sale {money(x['price'])} · Profit {money(x['profit'])} · {x['sold_at'][:16]}"
        )
    await message.answer("\n".join(lines))


@dp.message(Command("customers"))
async def customers(message: Message):
    if not await admin_only(message):
        return
    rows = db.customer_history()
    if not rows:
        await message.answer("No named customers recorded yet.")
        return
    lines = ["👥 CUSTOMER HISTORY"]
    for x in rows[:50]:
        lines.append(
            f"{x['customer']} · {x['orders']} sale(s) · Revenue {money(x['revenue'])}"
        )
    await message.answer("\n".join(lines))


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it in your .env file.")
    if not ADMIN_ID:
        raise RuntimeError("ADMIN_ID is missing. Set your numeric Telegram user ID in .env.")
    db.initialize()
    bot = Bot(TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
