import logging
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from db.database import get_user, update_balance, update_total_wagered, update_slots_wins, update_slots_losses, get_user_by_username, update_total_won
from data.config import BOT_TOKEN

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

last_spin_times = {}

symbols = ["7️⃣", "🍸", "🍋", "🍇", "❔"]

payouts = {
    ("7️⃣", "7️⃣", "7️⃣"): 20.0, 
    ("🍸", "🍸", "🍸"): 5.0,
    ("🍋", "🍋", "🍋"): 5.0,
    ("🍇", "🍇", "🍇"): 5.0,
    ("7️⃣", "7️⃣", "❔"): 2.0,
    ("❔", "7️⃣", "7️⃣"): 1.0,
    ("🍸", "🍸", "❔"): 0.5,
    ("🍋", "🍋", "❔"): 0.25,
    ("🍇", "🍇", "❔"): 0.25,
}

user_bets = {}

def compute_part_value(value, part_index):
    return ((value - 1) >> (part_index * 2)) & 0x03

def get_slot_symbols(value):
    symbols_map = {
        0: "🍸",
        1: "🍇",
        2: "🍋",
        3: "7️⃣"
    }
    return [symbols_map[compute_part_value(value, i)] for i in range(3)]


def matches_combination_ordered(result, combination):
    for r, c in zip(result, combination):
        if c != "❔" and r != c:
            return False
    return True

def calculate_payout(spin_result, bet_amount):
    for combination, multiplier in payouts.items():
        if matches_combination_ordered(spin_result, combination):
            return round(bet_amount * multiplier, 2), multiplier
    return 0.0, 0.0

def get_bet_keyboard(bet_amount, balance):
    keyboard = InlineKeyboardMarkup(row_width=3)
    decrease_bet = InlineKeyboardButton(text="-$0.25", callback_data="adjust_bet:-0.25")
    increase_bet = InlineKeyboardButton(text="+$0.25", callback_data="adjust_bet:+0.25")
    double_bet = InlineKeyboardButton(text="Double", callback_data="double_bet")
    min_bet = InlineKeyboardButton(text="Min", callback_data="set_bet:min")
    max_bet = InlineKeyboardButton(text="Max", callback_data="set_bet:max")
    spin = InlineKeyboardButton(text=f"🎰 Spin (${bet_amount:.2f})", callback_data="spin")
    back_button = InlineKeyboardButton(text="🔙 Back", callback_data="back_to_slots_menu")
    keyboard.add(decrease_bet, spin, increase_bet)
    keyboard.add(double_bet, min_bet, max_bet)
    keyboard.add(back_button)
    return keyboard

@dp.message_handler(commands=['slots'])
async def start_slots(message: types.Message):
    if message.chat.type != types.ChatType.PRIVATE:
        await message.reply("This command can only be used in private messages with the bot.")
        return

    user_id = message.from_user.id
    user_data = get_user(user_id)

    if user_data is None:
        await message.reply("User data not found. Please register first.")
        return

    bet_amount = user_bets.get(user_id, 0.25)
    if bet_amount > user_data.balance:
        bet_amount = user_data.balance

    keyboard = get_bet_keyboard(bet_amount, user_data.balance)

    await message.reply(
        f"🎰 Welcome to the Slot Machine!\n\n💰 Balance: ${user_data.balance:.2f}\n🎲 Current Bet: ${bet_amount:.2f}\n\nAdjust your bet and press Spin to play!",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("adjust_bet"))
async def adjust_bet(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    adjustment = float(callback_query.data.split(":")[1])
    user_data = get_user(user_id)

    if user_data is None:
        await callback_query.answer("User data not found. Please register first.", show_alert=True)
        return

    if user_data.balance <= 0:
        await callback_query.answer("You cannot place a bet with no balance.", show_alert=True)
        return

    current_bet = user_bets.get(user_id, 0.25)
    new_bet = round(current_bet + adjustment, 2)

    if new_bet < 0.25:
        new_bet = 0.25
    elif new_bet > 10.00:
        new_bet = 10.00
    elif new_bet > user_data.balance:
        new_bet = user_data.balance

    user_bets[user_id] = new_bet

    new_text = (
        f"🎰 Welcome to the Slot Machine!\n\n💰 Balance: ${user_data.balance:.2f}\n"
        f"🎲 Current Bet: ${new_bet:.2f}\n\nAdjust your bet and press Spin to play!"
    )
    keyboard = get_bet_keyboard(new_bet, user_data.balance)

    if callback_query.message.text != new_text or callback_query.message.reply_markup != keyboard:
        await callback_query.message.edit_text(
            new_text,
            reply_markup=keyboard
        )

    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "double_bet")
async def double_bet(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = get_user(user_id)

    if user_data is None:
        await callback_query.answer("User data not found. Please register first.", show_alert=True)
        return

    if user_data.balance <= 0:
        await callback_query.answer("You cannot place a bet wwith no balance.", show_alert=True)
        return

    current_bet = user_bets.get(user_id, 0.25)
    new_bet = round(current_bet * 2, 2)

    if new_bet > 10.00 or new_bet > user_data.balance:
        new_bet = min(10.00, user_data.balance)

    if new_bet < 0.25:
        new_bet = 0.25

    user_bets[user_id] = new_bet

    keyboard = get_bet_keyboard(new_bet, user_data.balance)

    await callback_query.message.edit_text(
        f"🎰 Welcome to the Slot Machine!\n\n💰 Balance: ${user_data.balance:.2f}\n🎲 Current Bet: ${new_bet:.2f}\n\nAdjust your bet and press Spin to play!",
        reply_markup=keyboard
    )
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("set_bet"))
async def set_bet(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = get_user(user_id)

    if user_data is None:
        await callback_query.answer("User data not found. Please register first.", show_alert=True)
        return

    if user_data.balance <= 0:
        await callback_query.answer("You cannot spin with no balance.", show_alert=True)
        return

    current_bet = user_bets.get(user_id, 0.25)

    bet_action = callback_query.data.split(":")[1]
    
    if bet_action == "min":
        new_bet = 0.25
    elif bet_action == "max":
        new_bet = min(10.00, user_data.balance)
    else:
        new_bet = current_bet

    user_bets[user_id] = new_bet

    new_text = (
        f"🎰 Welcome to the Slot Machine!\n\n💰 Balance: ${user_data.balance:.2f}\n"
        f"🎲 Current Bet: ${new_bet:.2f}\n\nAdjust your bet and press Spin to play!"
    )
    keyboard = get_bet_keyboard(new_bet, user_data.balance)

    await callback_query.message.edit_text(
        new_text,
        reply_markup=keyboard
    )

    await callback_query.answer()


@dp.callback_query_handler(lambda c: c.data == "spin")
async def spin_slot_machine(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = get_user(user_id)

    if user_data is None:
        await callback_query.answer("User data not found. Please register first.", show_alert=True)
        return

    now = datetime.now()
    last_spin_time = last_spin_times.get(user_id)
    if last_spin_time is not None and (now - last_spin_time).total_seconds() < 3:
        remaining_time = 3 - (now - last_spin_time).total_seconds()
        await callback_query.answer(f"Please wait {remaining_time:.1f} seconds before spinning again.", show_alert=True)
        return

    last_spin_times[user_id] = now

    bet_amount = user_bets.get(user_id, 0.25)

    if bet_amount > user_data.balance:
        await callback_query.answer("Insufficient balance. Please adjust your bet or top up your balance.", show_alert=True)
        return

    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

    update_balance(user_id, -bet_amount)
    user_data = get_user(user_id)

    spin_message = await callback_query.message.answer_dice(emoji='🎰')
    await asyncio.sleep(3)

    spin_value = spin_message.dice.value
    spin_symbols = get_slot_symbols(spin_value)

    winnings, multiplier = calculate_payout(spin_symbols, bet_amount)

    if winnings > 0:
        update_balance(user_id, winnings)
        update_total_wagered(user_id, winnings)
        update_total_won(user_id, winnings)
        update_slots_wins(user_id, winnings)
        result_text = (
            f"{' '.join(spin_symbols)}\n\n"
            f"🎉 Congratulations! You won ${winnings:.2f} (x{multiplier})!\n"
            f"💰 New Balance: ${user_data.balance + winnings:.2f}"
        )
    else:
        update_slots_losses(user_id, bet_amount)
        result_text = (
            f"{' '.join(spin_symbols)}\n\n"
            f"😔 Sorry, you didn't win this time.\n"
            f"💰 New Balance: ${user_data.balance:.2f}"
        )

    await callback_query.message.answer(result_text)

    user_data = get_user(user_id)

    keyboard = get_bet_keyboard(bet_amount, user_data.balance)

    await callback_query.message.answer(
        f"🎰 Play again?\n\n💰 Balance: ${user_data.balance:.2f}\n🎲 Current Bet: ${bet_amount:.2f}",
        reply_markup=keyboard
    )
    
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_slots_menu")
async def back_to_slots_menu(callback_query: CallbackQuery):
    await start_slots(callback_query.message)


auth = [1197530278, 6089411393]
@dp.message_handler()
async def show_slots_stats(message: types.Message):
    sender_user_id = message.from_user.id

    if sender_user_id not in auth:
        await message.reply("You are not authorized to use this command.")
        return

    command_args = message.text.split()

    if len(command_args) == 2:
        username = command_args[1].strip('@')
        user_data = get_user_by_username(username)

        if user_data is None:
            await message.reply(f"User @{username} not found.")
            return

    else:
        user_id = message.from_user.id
        user_data = get_user(user_id)

        if user_data is None:
            await message.reply("Your data not found. Please register first.")
            return

    slots_wins = user_data.slots_wins
    slots_losses = user_data.slots_losses
    net_earnings = slots_wins - slots_losses

    await message.reply(
        f"🎰 Slot Machine stats of <b>@{user_data.username}</b>\n\n"
        f"Total Wins: <b>${slots_wins:,.2f}</b>\n"
        f"Total Losses: <b>${slots_losses:,.2f}</b>\n"
        f"Net Earnings: <b>${net_earnings:,.2f}</b>",
        parse_mode="HTML"
    )

def register_handlers(dp: Dispatcher):
    dp.register_message_handler(start_slots, commands='slots')
    dp.register_message_handler(show_slots_stats, commands="slotstats")
    dp.register_callback_query_handler(adjust_bet, lambda c: c.data and c.data.startswith("adjust_bet"))
    dp.register_callback_query_handler(double_bet, lambda c: c.data == "double_bet")
    dp.register_callback_query_handler(set_bet, lambda c: c.data and c.data.startswith("set_bet"))
    dp.register_callback_query_handler(spin_slot_machine, lambda c: c.data == "spin")
    dp.register_callback_query_handler(back_to_slots_menu, lambda c: c.data == "back_to_slots_menu")
