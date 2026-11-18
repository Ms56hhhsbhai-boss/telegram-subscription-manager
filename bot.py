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
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from database import Database

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MONGODB_URI = os.getenv("MONGODB_URI", "")

logging.basicConfig(level=logging.INFO)
db = Database(MONGODB_URI)
dp = Dispatcher()


class AddStock(StatesGroup):
    photo = State()
    details = State()
    supplier = State()


class SellItem(StatesGroup):
    item_id = State()
    buying_price = State()
    price = State()
    warranty = State()
    customer = State()


class AddExpense(StatesGroup):
    description = State()
    amount = State()


class ResetData(StatesGroup):
    confirm = State()


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
        "⚡ SCARFACE CONTROL\n\n"
        "Welcome to your command centre.\n\n"
        "Your inventory. Your business. Your control.\n\n"
        "PRIVATE ACCESS • SYSTEM ONLINE"
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
    await state.set_state(AddStock.photo)
    await message.answer("Send an account screenshot/photo now, or send /skip to continue without a photo.")


@dp.message(AddStock.photo, F.photo)
async def addstock_photo(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    caption = (message.caption or "").strip()
    if caption:
        if len(caption) > 3000:
            await message.answer("The caption is too long. Please send the photo with a shorter caption (up to 3000 characters).")
            return
        await state.update_data(details=caption)
        await state.set_state(AddStock.supplier)
        await message.answer("✅ Photo and account details received together as one post. Who did you buy this account from? Enter the seller's name/reference:")
    else:
        await state.set_state(AddStock.details)
        await message.answer("Photo saved. Now paste the complete account details, or send the photo again with the details in its caption to submit them together as one post:")


@dp.message(AddStock.photo, Command("skip"))
async def addstock_skip_photo(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    await state.update_data(photo_file_id=None)
    await state.set_state(AddStock.details)
    await message.answer("No photo attached. Paste the complete account details (up to 3000 characters; multiple lines are supported):")


@dp.message(AddStock.photo)
async def addstock_photo_invalid(message: Message):
    if await admin_only(message):
        await message.answer("Please send a photo, or /skip to continue without one.")


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
    data = await state.get_data()
    try:
        item_id = db.add_inventory(data["details"], data["supplier"], photo_file_id=data.get("photo_file_id"))
    except Exception:
        logging.exception("Could not add account record")
        await message.answer("Could not add this account record. It may already exist. Try /addstock again.")
        await state.clear()
        return
    await state.clear()
    await message.answer(
        f"✅ ACCOUNT ADDED\nID: #{item_id}\nDetails saved as a message.\n"
        f"Supplier: {data['supplier']}\nBuying price will be entered when you use /sell."
    )


@dp.message(Command("stock"))
async def stock(message: Message):
    if not await admin_only(message):
        return
    items = db.available_inventory()
    if not items:
        await message.answer("Your inventory is empty.")
        return
    await message.answer(f"📦 AVAILABLE INVENTORY — {len(items)} account(s)")
    for item in items[:60]:
        text = (
            f"📦 ACCOUNT #{item['id']}\n"
            f"Status: AVAILABLE\n\n"
            f"Account details:\n{item['name']}"
        )
        if item.get("photo_file_id"):
            await message.answer_photo(item["photo_file_id"], caption=text[:1024])
            if len(text) > 1024:
                await message.answer(text[1024:])
        else:
            await message.answer(text)
    if len(items) > 60:
        await message.answer(f"Showing first 60 of {len(items)} accounts.")

@dp.message(Command("purchases"))
async def purchases(message: Message):
    if not await admin_only(message):
        return
    items = db.all_inventory(60)
    if not items:
        await message.answer("No purchase records yet. Add an account with /addstock.")
        return
    await message.answer(f"🛒 PURCHASE RECORDS — {len(items)} account(s)\nShowing sold and available accounts with purchase details.")
    for item in items:
        status = "SOLD" if item.get("status") == "sold" else "AVAILABLE"
        added = (item.get("added_at") or "")[:16].replace("T", " ")
        text = (
            f"🛒 ACCOUNT #{item['id']}\n"
            f"Status: {status}\n\n"
            f"Account details:\n{item['name']}\n\n"
            f"Bought from: {item.get('supplier') or 'Not specified'}\n"
            f"Buying price: {money(item.get('cost')) if item.get('cost') else 'Entered when sold'}\n"
            f"Purchased on: {added or 'Not specified'}"
        )
        if item.get("photo_file_id"):
            await message.answer_photo(item["photo_file_id"], caption=text[:1024])
            if len(text) > 1024:
                await message.answer(text[1024:])
        else:
            await message.answer(text)
    if len(items) >= 60:
        await message.answer("Showing the latest 60 purchase records.")

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
    lines += [f"#{x['id']} · {x.get('supplier') or 'Supplier not specified'}" for x in items[:50]]
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
    await state.set_state(SellItem.buying_price)
    await message.answer(
        f"Selected account #{item_id}\n\n{item['name'][:2500]}\n\n"
        f"Supplier: {item.get('supplier') or 'Not specified'}\n\n"
        "Enter the buying price you paid for this account:"
    )


@dp.message(SellItem.buying_price)
async def sell_buying_price(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer("Enter a valid positive buying price.")
        return
    await state.update_data(buying_price=str(amount))
    await state.set_state(SellItem.price)
    await message.answer("Enter the selling price charged to the customer:")


@dp.message(SellItem.price)
async def sell_price(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer("Enter a valid positive selling price.")
        return
    await state.update_data(price=str(amount))
    await state.set_state(SellItem.warranty)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="2M", callback_data="warranty:2_months")],
        [InlineKeyboardButton(text="1M", callback_data="warranty:1_month")],
        [InlineKeyboardButton(text="No Warranty", callback_data="warranty:none")],
    ])
    await message.answer("Choose the warranty period:", reply_markup=keyboard)


@dp.callback_query(SellItem.warranty, F.data.startswith("warranty:"))
async def sell_warranty(callback: CallbackQuery, state: FSMContext):
    if not ADMIN_ID or callback.from_user.id != ADMIN_ID:
        await callback.answer("Private admin only.", show_alert=True)
        return
    warranty = callback.data.split(":", 1)[1]
    labels = {"2_months": "2M", "1_month": "1M", "none": "No Warranty"}
    if warranty not in labels:
        await callback.answer("Invalid warranty selection.", show_alert=True)
        return
    await state.update_data(warranty=labels[warranty])
    await state.set_state(SellItem.customer)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"Warranty: {labels[warranty]}\nEnter customer name or reference (or type - to skip):")
    await callback.answer()


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
    result = db.record_sale(data["item_id"], Decimal(data["buying_price"]), Decimal(data["price"]), customer, data["warranty"])
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
        f"Buying price: {money(result['cost'])}\n"
        f"Warranty: {result['warranty']}\n"
        f"Gross profit: {money(result['profit'])}"
    )


@dp.message(Command("replacement"))
async def replacement(message: Message):
    if not await admin_only(message):
        return
    rows = db.active_warranty_sales(limit=100)
    if not rows:
        await message.answer("No accounts currently have an active 1M or 2M warranty.")
        return
    await message.answer(f"🔁 ACTIVE WARRANTY REPLACEMENTS — {len(rows)} account(s)")
    for row in rows:
        status = row.get("replacement_status", "Pending")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Pending", callback_data=f"replacement:{row['id']}:Pending"),
             InlineKeyboardButton(text="Done", callback_data=f"replacement:{row['id']}:Done")]
        ])
        details = (
            f"🔁 SALE #{row['id']} · ACCOUNT #{row.get('inventory_id', '?')}\n"
            f"Account: {row.get('item_name', 'Not recorded')}\n"
            f"Customer: {row.get('customer') or 'Not specified'}\n"
            f"Sold: {row.get('sold_at', '')[:10]}\n"
            f"Warranty: {row.get('warranty', '')}\n"
            f"Warranty expires: {row.get('warranty_expires', '')}\n"
            f"Replacement: {status}"
        )
        await message.answer(details, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("replacement:"))
async def replacement_status(callback: CallbackQuery):
    if not ADMIN_ID or callback.from_user.id != ADMIN_ID:
        await callback.answer("Private admin only.", show_alert=True)
        return
    try:
        _, sale_id, status = callback.data.split(":", 2)
        sale_id = int(sale_id)
    except (ValueError, AttributeError):
        await callback.answer("Invalid selection.", show_alert=True)
        return
    ok, result = db.set_replacement_status(sale_id, status)
    if not ok:
        await callback.answer(result, show_alert=True)
        return
    # Refresh button labels to make the saved status obvious.
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Pending ✓" if status == "Pending" else "Pending", callback_data=f"replacement:{sale_id}:Pending"),
         InlineKeyboardButton(text="Done ✓" if status == "Done" else "Done", callback_data=f"replacement:{sale_id}:Done")]
    ])
    text = callback.message.text or ""
    if "Replacement:" in text:
        text = text.rsplit("Replacement:", 1)[0] + f"Replacement: {status}"
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer(f"Replacement marked {status}.")


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
    await message.answer(f"🧾 RECENT SALES — {len(rows)} record(s)")
    for x in rows:
        text = (
            f"🧾 SALE #{x['id']}\n"
            f"Status: SOLD\n\n"
            f"Account details:\n{x['name']}\n\n"
            f"Bought from: {x['supplier'] or 'Not specified'}\n"
            f"Purchase cost: {money(x['cost'])}\n"
            f"Sold to: {x['customer'] or 'Not specified'}\n\n"
            f"Buying price: {money(x['cost'])}\n"
            f"Selling price: {money(x['price'])}\n"
            f"Warranty: {x.get('warranty', 'Not recorded')}\n"
            f"Profit: {money(x['profit'])}\n"
            f"Sold on: {x['sold_at'][:16].replace('T', ' ')}"
        )
        if x.get("photo_file_id"):
            await message.answer_photo(x["photo_file_id"], caption=text[:1024])
            if len(text) > 1024:
                await message.answer(text[1024:])
        else:
            await message.answer(text)


@dp.message(Command("resetdata"))
async def resetdata(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    await state.clear()
    await state.set_state(ResetData.confirm)
    await message.answer(
        "⚠️ DELETE ALL TEST RECORDS?\n\n"
        "This permanently clears inventory, sales, customers, and expenses.\n"
        "Your MongoDB database and Heroku configuration remain.\n\n"
        "To confirm, reply exactly: DELETE ALL\n"
        "To keep your records, send /cancel."
    )


@dp.message(ResetData.confirm)
async def resetdata_confirm(message: Message, state: FSMContext):
    if not await admin_only(message):
        return
    answer = (message.text or "").strip()
    if answer != "DELETE ALL":
        await state.clear()
        await message.answer("Reset cancelled. Your records were not changed.")
        return
    try:
        counts = db.reset_all_data()
    except Exception:
        logging.exception("Could not clear test records")
        await state.clear()
        await message.answer("❌ Could not clear records. Nothing was confirmed as deleted; check Heroku logs.")
        return
    await state.clear()
    await message.answer(
        "✅ TEST RECORDS CLEARED\n\n"
        f"Inventory records deleted: {counts['inventory']}\n"
        f"Sales records deleted: {counts['sales']}\n"
        f"Customer records deleted: {counts['customers']}\n"
        f"Expense records deleted: {counts['expenses']}\n\n"
        "Your database and bot configuration are still in place."
    )

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
