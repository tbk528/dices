import logging, uuid, requests, locale, asyncio, aiohttp, os, json
from bs4 import BeautifulSoup
from peewee import fn
from datetime import datetime, timedelta
import random, string
from aiogram import Dispatcher, types, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from db.models import User, Match, Profits
from db.models import ClaimCode
import time
from datetime import datetime
from math import ceil
from .mines import user_games
from data.config import ADMINS
from db.database import get_user, update_balance, get_user_by_username, get_user_raffle_tickets, get_raffle_pool, purchase_raffle_ticket, draw_raffle_winner
from data.config import STARTING_BALANCE, BTCPAY_STORE_ID, BTCPAY_URL, BTCPAY_API_KEY, REFERRAL_REWARD_PERCENTAGE, BOT_TOKEN, EXCHANGE_API_URL, EXCHANGE_ID, STATE
from config import ADMINS
timestamp = datetime.now()
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())
file_lock = asyncio.Lock()

async def raffle_stats(message: types.Message):
    user_id = message.from_user.id

    # Get user's ticket count
    user_tickets = get_user_raffle_tickets(user_id)
    tickets_count = user_tickets.tickets

    # Get overall raffle stats
    raffle_pool = get_raffle_pool()
    total_tickets = raffle_pool.total_tickets
    prize_pool = raffle_pool.total_pool

    # Format response message
    response_message = (
        f"🎟️ <b>Raffle Stats</b>\n\n"
        f"Your Tickets: <b>{tickets_count}</b>\n"
        f"Total Tickets in Raffle: <b>{total_tickets}</b>\n"
        f"Prize Pool: <b>${prize_pool:.2f}</b>"
    )

    # Create inline keyboard for purchasing or selling tickets
    keyboard = InlineKeyboardMarkup(row_width=2)
    buy_button = InlineKeyboardButton(text="🎫 Purchase Tickets", callback_data="raffle_buy")
    sell_button = InlineKeyboardButton(text="💸 Sell Tickets", callback_data="raffle_sell")
    keyboard.add(buy_button, sell_button)

    await message.reply(response_message, parse_mode="HTML", reply_markup=keyboard)

# Handle ticket purchase callback
async def raffle_buy_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    # Attempt to purchase 1 ticket (for simplicity; we could expand for different quantities)
    success, message = purchase_raffle_ticket(user_id, num_tickets=1)
    await callback_query.answer(message, show_alert=True)

# Handle ticket sell callback (sells one ticket as a simple example)
async def raffle_sell_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_tickets = get_user_raffle_tickets(user_id)

    if user_tickets.tickets > 0:
        # Define a sell price (this could be customized)
        TICKET_SELL_PRICE = 1.0  # Example ticket sell-back price
        user_tickets.tickets -= 1
        user_tickets.save()

        # Credit user's balance with the sell-back price (update_balance is assumed to exist)
        update_balance(user_id, TICKET_SELL_PRICE)
        message = f"Successfully sold 1 ticket for ${TICKET_SELL_PRICE}."
    else:
        message = "You have no tickets to sell!"

    await callback_query.answer(message, show_alert=True)

# Draw raffle winner (admin only)
async def draw_raffle_winner_command(message: types.Message):
    if str(message.from_user.id) not in ADMINS:
        await message.reply("🚫 You are not authorized to draw a raffle winner.")
        return

    # Draw the winner
    winner_id, result_message = draw_raffle_winner()
    if winner_id:
        await message.reply(f"🎉 {result_message}", parse_mode="HTML")
    else:
        await message.reply("No tickets sold yet, so no winner could be drawn.", parse_mode="HTML")

# Reset raffle (admin only)
async def reset_raffle_command(message: types.Message):
    if str(message.from_user.id) not in ADMINS:
        await message.reply("🚫 You are not authorized to reset the raffle leaderboard.")
        return

    # Resetting the raffle pool and user tickets
    raffle_pool = get_raffle_pool()
    raffle_pool.total_tickets = 0
    raffle_pool.total_pool = 0.0
    raffle_pool.save()

    # Reset each user's tickets
    for user_ticket in RaffleTickets.select():
        user_ticket.tickets = 0
        user_ticket.earned_by_wagering = 0
        user_ticket.save()

    await message.reply("✅ The raffle leaderboard has been reset.", parse_mode="HTML")




MINIMUM_WAGERED_TO_CLAIM = 50.0  # Minimum amount a user must wager before claiming a code
REQUIRED_STRING_IN_DISPLAY_NAME = "@DiceNight"  # Required string in the display name to claim codes

@dp.message_handler(commands=["createcode"])
async def create_code_handler(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    # Check if the user has an account
    if user is None:
        await message.reply("❌ You need to start the bot before creating codes.")
        return

    args = message.get_args().split()

    # Ensure the user provides both a code and the amount
    if len(args) < 2:
        await message.reply("Usage: /createcode <code> <amount>. Example: /createcode HELLO 5")
        return

    # Use the first argument as the code and the second as the balance
    code = args[0].strip().upper()  # Normalize the code input to uppercase
    try:
        balance = float(args[1])  # Ensure the second argument is a valid number
    except ValueError:
        await message.reply("❌ Invalid amount. Please provide a valid number for the balance.")
        return

    # Check if the user has enough balance to create the code
    if user.balance < balance:
        await message.reply(f"❌ You do not have enough balance to create this code. Your current balance is ${user.balance:.2f}.")
        return

    # Check if the code already exists
    existing_code = ClaimCode.get_or_none(ClaimCode.code == code)
    if existing_code:
        await message.reply(f"❌ A code with the value '{code}' already exists.")
        return

    # Deduct the balance from the user's account
    user.balance -= balance
    user.save()

    # Store the new code in the database with the specified balance
    ClaimCode.create(code=code, balance=balance, claimed=False, claimed_by=None, claimed_at=None)

    await message.reply(
        f"✅ Code created! The code is: <b>{code}</b> and can be claimed for ${balance:.2f}.\n"
        f"💰 Your new balance is ${user.balance:.2f}.",
        parse_mode="HTML"
    )

user_command_timestamps = {}

@dp.message_handler(commands=["claim"])
async def claim_code_handler(message: types.Message):
    user_id = message.from_user.id
    current_time = time.time()
    cooldown_period = 5  # seconds

    # Rate limiting logic
    last_used = user_command_timestamps.get(user_id, 0)
    time_since_last_use = current_time - last_used

    if time_since_last_use < cooldown_period:
        remaining_time = int(cooldown_period - time_since_last_use)
        await message.reply(f"❌ Please wait {remaining_time} seconds before using this command again.")
        return

    # Update the last used timestamp
    user_command_timestamps[user_id] = current_time

    # Fetch user data
    user = get_user(user_id)
    if user is None:
        await message.reply("❌ You need to start the bot before claiming codes.")
        return

    # Get the user's full name (display name) from the message
    display_name = message.from_user.full_name or ""

    # Check if the user's display name contains the required string (case-insensitive)
    if REQUIRED_STRING_IN_DISPLAY_NAME.lower() not in display_name.lower():
        await message.reply(
            f"❌ To claim codes, your display name must include '{REQUIRED_STRING_IN_DISPLAY_NAME}'. "
            f"Your current display name is '{display_name}'."
        )
        return

    # Check if the user has wagered the minimum required amount
    if user.total_wagered < MINIMUM_WAGERED_TO_CLAIM:
        await message.reply(
            f"❌ You must wager at least ${MINIMUM_WAGERED_TO_CLAIM:.2f} before you can claim any codes.\n"
            f"💰 You have wagered: ${user.total_wagered:.2f}."
        )
        return

    # Get the code from the user's message
    args = message.get_args()
    if not args:
        await message.reply("❌ Please provide a claim code. Usage: /claim <code>")
        return

    code = args.strip().upper()  # Normalize code input

    # Search for the code in the database
    claim_code = ClaimCode.get_or_none(ClaimCode.code == code)
    if claim_code is None:
        await message.reply("❌ The code you entered is invalid. Please check and try again.")
        return

    # Check if the code has already been claimed
    if claim_code.claimed:
        await message.reply("❌ This code has already been claimed.")
        return

    # Update the user's balance and save
    user.balance += claim_code.balance
    user.save()

    # Mark the code as claimed and save
    claim_code.claimed = True
    claim_code.claimed_by = user_id
    claim_code.claimed_at = datetime.utcnow()
    claim_code.save()

    await message.reply(
        f"✅ Success! You have claimed ${claim_code.balance:.2f}.\n"
        f"💰 Your new balance is ${user.balance:.2f}."
    )



def load_profits_from_db():
    try:
        profits_record, created = Profits.get_or_create(id=1)
        return {
            "game_fee": profits_record.game_fee,
            "deposit_fee": profits_record.deposit_fee,
            "total_profit": profits_record.total_profit
        }
    except Exception as e:
        logging.error(f"Error loading profits from the database: {e}")
        return {"game_fee": 0.0, "deposit_fee": 0.0, "total_profit": 0.0}

profits = load_profits_from_db()

async def save_profits_to_db():
    try:
        async with file_lock:
            profits_record, created = Profits.get_or_create(id=1)
            profits_record.game_fee = profits["game_fee"]
            profits_record.deposit_fee = profits["deposit_fee"]
            profits_record.total_profit = profits["total_profit"]
            profits_record.last_updated = datetime.now()
            profits_record.save()
    except Exception as e:
        logging.error(f"Error saving profits to the database: {e}")

async def update_game_fee_profit(amount: float, user_id: int):
    profits["game_fee"] += amount
    profits["total_profit"] += amount
    await save_profits_to_db()

async def update_deposit_fee_profit(amount: float):
    profits["deposit_fee"] += amount
    profits["total_profit"] += amount
    await save_profits_to_db()

def get_profit_summary():
    profits_record = Profits.get_or_none(id=1)
    if profits_record:
        return {
            "game_fee": profits_record.game_fee,
            "deposit_fee": profits_record.deposit_fee,
            "total_profit": profits_record.total_profit
        }
    else:
        return {"game_fee": "$0.0", "deposit_fee": "$0.0", "total_profit": "$0.0"}

async def check_bot_stats(message: types.Message):
    restricted_bot_username = "dicenightsdealerbot"

    if str(message.from_user.id) not in auth:
        return

    user_data = get_user_by_username(restricted_bot_username)

    if user_data is None:
        await message.reply("Error: Unable to retrieve the stats of the bot. Please try again later.")
        return

    total_wagered = user_data.total_wagered if user_data.total_wagered is not None else 0.0
    wins = user_data.wins if user_data.wins is not None else 0
    losses = user_data.losses if user_data.losses is not None else 0
    total_won = user_data.total_won if user_data.total_won is not None else 0.0

    total_games = wins + losses
    win_percentage = (wins / total_games * 100) if total_games > 0 else 0.0

    user_level = "Dealer Bot 🤖"

    stats_message = (
        f"ℹ️ Stats of <b>@{restricted_bot_username}</b>\n\n"
        f"Level: <b>{user_level}</b>\n"
        f"Games Played: <b>{total_games:,}</b>\n"
        f"Wins: <b>{wins}</b> ({win_percentage:.2f}%)\n"
        f"Total Wagered: <b>${total_wagered:,.2f}</b>\n"
        f"Total Won: <b>${total_won:,.2f}</b>\n"
    )

    await message.reply(stats_message, parse_mode="HTML")


def load_state(user_id):
    try:
        with open(STATE, 'r') as file:
            states = json.load(file)
    except FileNotFoundError:
        states = {}
    return states.get(str(user_id), {})
def save_state(user_id, state):
    try:
        with open(STATE, 'r') as file:
            states = json.load(file)
    except FileNotFoundError:
        states = {}
    states[str(user_id)] = state
    with open(STATE, 'w') as file:
        json.dump(states, file)
def delete_state(user_id):
    try:
        with open(STATE, 'r') as file:
            states = json.load(file)
    except FileNotFoundError:
        return
    if str(user_id) in states:
        del states[str(user_id)]
        with open(STATE, 'w') as file:
            json.dump(states, file)

async def get_ltc_to_usd():
    async with aiohttp.ClientSession() as session:
        async with session.get('https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd') as response:
            data = await response.json()
            return data['litecoin']['usd']

async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="/start", description="🏠 Open main menu"),
        BotCommand(command="/balance", description="💰 Check balance"),
        BotCommand(command="/dice", description="🎲 Play dice"),
        BotCommand(command="/bask", description="🏀 Play basketball"),
        BotCommand(command="/bowl", description="🎳 Play bowling"),
        BotCommand(command="/darts", description="🎯 Play darts"),
        BotCommand(command="/ball", description="⚽ Play football"),
        BotCommand(command="/slots", description="🎰 Play slot machine"),
        BotCommand(command="/mines", description="💣 Play Mines"),
        BotCommand(command="/Connect", description="✅ Play Connect4"),
        BotCommand(command="/Tic", description="❌ Play TicTacToe"),
        BotCommand(command="/coinflip", description="🪙 Play coinflip"),
        BotCommand(command="/leaderboard", description="🏆 Check leaderboard"),
        BotCommand(command="/tip", description="💸 Tip someone"),
        BotCommand(command="/referral", description="🤝 Invite your friends"),
        BotCommand(command="/housebal", description="🏦 View bot balance"),
        BotCommand(command="/stats", description="📊 Your statistics"),
        BotCommand(command="/deposit", description="📈 Top-up your account"),
        BotCommand(command="/withdraw", description="📉 Withdraw your well-earned money"),
        BotCommand(command="/matches", description="📆 View bet history"),
        BotCommand(command="/help", description="❔ Bot guide"),
    ]
    await bot.set_my_commands(commands)

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    user_data = get_user(user_id)

    # Extract referral code from the command arguments
    args = message.get_args()
    referred_by = None

    if args:
        referral_code = args.strip()
        referrer = User.get_or_none(User.referral_code == referral_code)
        if referrer and referrer.id != user_id:
            referred_by = referrer.referral_code
            referrer.invited_users = (referrer.invited_users or 0) + 1
            referrer.save()
    
    if not user_data:
        # Create a new user with a starting balance and referral code
        update_balance(user_id, STARTING_BALANCE, username)
        user_data = get_user(user_id)
        user_data.referred_by = referred_by
        user_data.save()
    else:
        # Update username if it has changed
        if username != user_data.username:
            user_data.username = username
            user_data.save()

    if args == "deposit":
        await deposit_handler(message)
        return

    # Get bot info for buttons
    bot_info = await bot.get_me()
    bot_username = bot_info.username

    # Inline keyboard setup with buttons for Play, Deposit, Withdraw, Referral, and Updates
    keyboard = InlineKeyboardMarkup(row_width=2)
    play_button = InlineKeyboardButton(text="🎮 Play", url="https://t.me/DiceNight")  # Link to your group chat
    deposit_button = InlineKeyboardButton(text="💳 Deposit", callback_data="trigger_deposit")
    withdraw_button = InlineKeyboardButton(text="🏦 Withdraw", callback_data="trigger_withdraw")
    referral_button = InlineKeyboardButton(text="📧 Referral", callback_data="trigger_referral")
    updates_button = InlineKeyboardButton(text="📢 Updates", url="https://t.me/DiceNights")  # Link to your updates channel

    keyboard.add(play_button)
    keyboard.add(deposit_button, withdraw_button)
    keyboard.add(referral_button, updates_button)

    # Menu with available game commands and balance
    formatted_balance = format_balance(user_data.balance)

    await message.reply(
        f"🎮 Welcome to <b>DiceNights</b>! Your balance is <b>{formatted_balance}</b>\n\n"
        "Below is a list of commands to use:\n\n"
        "• 🎲 <b>/dice</b> - Play Dice game\n"
        "• 🏀 <b>/bask</b> - Play Basketball game\n"
        "• 🎳 <b>/bowl</b> - Play Bowling game\n"
        "• 🎯 <b>/darts</b> - Play Darts game\n"
        "• ⚽️ <b>/ball</b> - Play Soccer game\n"
        "• 🎰 <b>/slots</b> - Slot machine\n"
        "• 🪙 <b>/coinflip</b> - Coinflip game\n"
        "• ✅ <b>/connect</b> - Connect4 game\n"
        "• ❌ <b>/tic</b> - TicTactoe game\n"
        "• 💣 <b>/mines</b> - Mines game\n\n"
        "<b>⚠️ DISCLAIMER:</b> Gambling involves risk. Please only gamble with funds that you can comfortably afford to lose. <b>Stay Safe!</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# Define callback handlers for deposit, withdraw, and referral actions
@dp.callback_query_handler(lambda c: c.data == "deposit")
async def deposit_handler(callback_query: types.CallbackQuery):
    await callback_query.message.reply("To deposit funds, use the /deposit command.")

@dp.callback_query_handler(lambda c: c.data == "withdraw")
async def withdraw_handler(callback_query: types.CallbackQuery):
    await callback_query.message.reply("To withdraw funds, use the /withdraw command.")

async def referral_handler(callback_query: types.CallbackQuery):
    await bot.send_message(
        chat_id=callback_query.from_user.id,  # Send a message to the user's chat
        text="To refer friends, use the /referral command."
    )

async def show_stats(message: types.Message):
    command_args = message.text.split()

    # If a username is provided
    if len(command_args) == 2:
        username_to_search = command_args[1].lstrip('@')  # Strip '@' and make lowercase
        user_data = get_user_by_username(username_to_search)

        if not user_data:
            await message.reply(f"User @{username_to_search} not found.")
            return
    else:
        # Fallback to the user executing the command if no username is provided
        user_id = message.from_user.id
        user_data = get_user(user_id)

        if not user_data:
            await message.reply("You need to start the bot first by using the /start command.")
            return

    # Default values if fields are missing
    username = user_data.username or "Unknown"
    total_wagered = user_data.total_wagered if user_data.total_wagered is not None else 0.0
    wins = user_data.wins if user_data.wins is not None else 0
    losses = user_data.losses if user_data.losses is not None else 0
    total_won = user_data.total_won if user_data.total_won is not None else 0.0

    total_games = wins + losses
    win_percentage = (wins / total_games * 100) if total_games > 0 else 0.0

    if user_data.id == 9999:
        user_level = "Dealer Bot 🤖"
    else:
        user_level = get_user_level(total_wagered)

    stats_message = (
        f"ℹ️ Stats of <b>@{username}</b>\n\n"
        f"Level: <b>{user_level}</b>\n"
        f"Games Played: <b>{total_games:,}</b>\n"
        f"Wins: <b>{wins}</b> ({win_percentage:.2f}%)\n"
        f"Total Wagered: <b>${total_wagered:,.2f}</b>\n"
        f"Total Won: <b>${total_won:,.2f}</b>\n"
    )

    await message.reply(stats_message, parse_mode="HTML")



level_thresholds = [
    (0, "Bronze"),
    (1000, "Silver 🦔"),
    (5000, "Gold 🐂"),
    (10000, "Diamond 🐻"),
    (20000, "Platinum 🦈"),
    (50000, "Black 🐳"),
]

async def check_balance(message: types.Message):
    command_args = message.text.split()

    bot_info = await bot.get_me()  # Fetch bot's info (used for generating links)

    # Check if a username is provided in the command
    if len(command_args) == 2:
        username = command_args[1].strip('@')  # Strip '@' and ensure case insensitivity
        user_data = get_user_by_username(username)

        if user_data is None:
            await message.reply(f"User @{username} not found.")
            return
    else:
        # Fallback to the user executing the command if no username is provided
        user_id = message.from_user.id
        user_data = get_user(user_id)

        if user_data is None or user_data.balance is None:
            await message.reply("Error: Unable to retrieve your balance. Please try again later.")
            return

    # Format the user's balance for display
    formatted_balance = format_balance(user_data.balance)

    # Create a keyboard for deposit/withdraw (works in both private/public chats)
    keyboard = InlineKeyboardMarkup(row_width=2)
    if message.chat.type == 'private':  # If the message is in a private chat
        deposit_button = InlineKeyboardButton(text="💳 Deposit", callback_data='trigger_deposit')
        withdraw_button = InlineKeyboardButton(text="💸 Withdraw", callback_data='trigger_withdraw')
    else:  # For group chats, provide bot link for deposit/withdraw
        deposit_button = InlineKeyboardButton(text="💳 Deposit", url=f"https://t.me/{bot_info.username}")
        withdraw_button = InlineKeyboardButton(text="💸 Withdraw", url=f"https://t.me/{bot_info.username}")
    keyboard.add(deposit_button, withdraw_button)

    # Send the balance information only once
    await message.reply(
        f"<b>@{user_data.username}</b>'s balance: <b>{formatted_balance}</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


def get_user_level(total_wagered):
    for threshold, level in reversed(level_thresholds):
        if total_wagered >= threshold:
            return level
    return "Beginner ❔"

async def handle_private_chat_action(callback_query: types.CallbackQuery, action):
    if callback_query.message.chat.type == 'private':
        chat_id = callback_query.from_user.id
        message_id = callback_query.message.message_id
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        await action(callback_query)
    else:
        await bot.send_message(callback_query.from_user.id, "<b>This action can only be performed in a private chat. Please message me directly.</b>", parse_mode="HTML")
    await callback_query.answer()

async def show_deposit_callback(callback_query: types.CallbackQuery):
    async def deposit_action(callback_query: types.CallbackQuery):
        await deposit_handler(callback_query.message)
    
    await handle_private_chat_action(callback_query, deposit_action)

async def show_withdraw_callback(callback_query: types.CallbackQuery):
    async def withdraw_action(callback_query: types.CallbackQuery):
        await withdraw_handler(callback_query.message)
    
    await handle_private_chat_action(callback_query, withdraw_action)

def get_user_balance(user_id):
    user = User.get_or_none(User.id == user_id)
    
    if user:
        return user.balance
    else:
        return 0.0
    


@dp.callback_query_handler(lambda c: c.data == 'trigger_referral')
async def trigger_referral(callback_query: types.CallbackQuery):
    # Answer the callback query (this prevents the loading spinner on the button from persisting)
    await callback_query.answer()

    # Call the referral handler
    await referral_handler(callback_query)  # Pass the callback query, not the message


@dp.callback_query_handler(lambda c: c.data == 'trigger_deposit')
async def trigger_deposit(callback_query: types.CallbackQuery):
    if callback_query.message.chat.type == 'private':
        await callback_query.answer()
        await deposit_handler(callback_query.message)

@dp.callback_query_handler(lambda c: c.data == 'trigger_withdraw')
async def trigger_withdraw(callback_query: types.CallbackQuery):
    if callback_query.message.chat.type == 'private':
        await callback_query.answer()
        await withdraw_handler(callback_query.message)

def calculate_win_percentage(wins, losses):
    total_games = wins + losses
    if total_games == 0:
        return 0.0
    return (wins / total_games) * 100

async def show_leaderboard(message: types.Message):
    try:
        leaderboard_data = (
            User
            .select(User.username, User.total_wagered, User.wins, User.losses)
            .order_by(User.total_wagered.desc())
            .limit(10)
        )

        if not leaderboard_data:
            await message.reply("No leaderboard data available.")
            return

        leaderboard_text = "🏆 All-Time Leaderboard Most Wagered:\n\n"
        for i, user in enumerate(leaderboard_data):
            win_percentage = calculate_win_percentage(user.wins, user.losses)
            leaderboard_text += (f"{i+1}. <b>{user.username}</b> - <b>${user.total_wagered:,.2f}</b> "
                                 f"(Win percentage: <b>{win_percentage:.2f}%</b>)\n")

        await message.reply(leaderboard_text, parse_mode="HTML")

    except Exception as e:
        await message.reply(f"An error occurred while fetching the leaderboard...")

def calculate_win_percentage(wins, losses):
    total_games = wins + losses
    if total_games == 0:
        return 0.0
    return (wins / total_games) * 100

async def tip_user(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split()
    user_id_str = str(user_id)

    if user_id_str in user_games:
        await message.reply("⚠️ You cannot tip while you have an active game. Please finish your game first.")
        logging.warning(f"User {user_id} attempted to use /tip while having an active game.")
        return

    state = load_state(user_id)

    logging.warning(f"User {user_id} state: {state}")

    if state.get('awaiting_amount'):
        await message.reply("You cannot use the <b>/tip</b> command while a withdrawal is awaiting for your amount.", parse_mode="HTML")
        return
    if state.get('requires_approval'):
        await message.reply("You cannot use the <b>/tip</b> command while a withdrawal is pending approval.", parse_mode="HTML")
        return

    if message.reply_to_message:
        recipient_id = message.reply_to_message.from_user.id
        recipient_username = message.reply_to_message.from_user.username
        
        if len(args) < 2:
            await message.reply("Usage: <b>/tip [amount]</b>", parse_mode="HTML")
            return

        try:
            amount = float(args[1])
        except ValueError:
            await message.reply("Invalid amount!")
            return

    else:
        if len(args) < 3:
            await message.reply("Usage: <b>/tip [username] [amount]</b>", parse_mode="HTML")
            return

        recipient_username = args[1].strip('@')
        try:
            amount = float(args[2])
        except ValueError:
            await message.reply("Invalid amount!")
            return

    if amount <= 0.01:
        await message.reply("<b>Tip amount must not be 0</b>", parse_mode="HTML")
        return

    if amount <= 0:
        await message.reply("<b>Tip amount must not be 0</b>", parse_mode="HTML")
        return

    sender = get_user(user_id)

    if message.reply_to_message:
        recipient = get_user(recipient_id)
    else:
        recipient = get_user_by_username(recipient_username)

    if recipient is None:
        await message.reply(f"<b>User @{recipient_username} not found!</b>", parse_mode="HTML")
        return

    if sender.balance < amount:
        await message.reply("<b>You don't have enough balance to tip!</b>", parse_mode="HTML")
        return

    update_balance(user_id, -amount)
    update_balance(recipient.id, amount)

    sender_balance_after = sender.balance - amount
    recipient_balance_after = recipient.balance + amount

    await message.reply(
        f"Successfully tipped <b>@{recipient.username if recipient_username else recipient.id}</b> amount of <b>${amount:,.2f}</b>\n"
        f"Your new balance is <b>${sender_balance_after:,.2f}</b> 💰", parse_mode="HTML"
    )

    await bot.send_message(
        recipient.id,
        f"You have received a tip of <b>${amount:,.2f}</b> from <b>@{message.from_user.username}</b>\n"
        f"Your new balance is <b>${recipient_balance_after:,.2f}</b> 💰", parse_mode="HTML"
    )

    log_message = (
        f"💰 <b>Tip Processed:</b>\n\n"
        f"Sender: <b>@{sender.username} (ID: {sender.id})</b>\n"
        f"Recipient: <b>@{recipient.username if recipient_username else recipient.id} (ID: {recipient.id})</b>\n"
        f"Amount: <b>${amount:.2f}</b>\n"
        f"Sender's New Balance: <b>${sender_balance_after:.2f}</b>\n"
        f"Recipient's New Balance: <b>${recipient_balance_after:.2f}</b>"
    )

    await bot.send_message(chat_id="-1002222833132", text=log_message, parse_mode="HTML")

async def show_help(message: types.Message):
    help_text = (
        "<b>How to play:</b>\n\n"
        "1. Go to our bot @DiceNightsBot\n"
        "2. Press start\n"
        "3. Press deposit\n"
        "4. Choose the crypto you want to deposit\n"
        "5. Send any amount to the address provided (Each address generated accepts only one payment)\n"
        "6. Wait until your deposit has been confirmed.\n"
        "7. Head over to @DiceNights and wait until accepted or gamble in your group of choice!\n"
        "8. Type /start or /help in chat.\n\n"
        
        "<b>🤖 Bot Commands:</b>\n\n"
        "<b>/start</b> - Start interacting with the bot and set up your account.\n"
        "<b>/balance</b> - Check your current balance.\n"
        "<b>/bet &lt;amount&gt;</b> - Place a bet with the specified amount. You can use 'all' or 'half' as shortcuts.\n"
        "<b>/leaderboard</b> - View the leaderboard of top players.\n"
        "<b>/tip &lt;username&gt; &lt;amount&gt;</b> - Tip another player with a specified amount.\n"
        "<b>/referral</b> - Get your referral link and view your referral stats.\n"
        "<b>/deposit</b> - Check the available deposit payment methods.\n"
        "<b>/withdraw</b> - Check the available withdrawal payment methods.\n"
        "<b>/housebalance</b> - View the house balance.\n"
        "<b>/stats</b> - View your personal stats (total wagered, wins, losses, win percentage, and level).\n"
        "<b>/help</b> - Show this help message with all available commands.\n\n"
        
        "<b>Normal Mode:</b> Higher number wins\n"
        "<b>Crazy Mode:</b> Lower number wins\n\n"
        
        "<b>⚠️DISCLAIMER:</b>\n"
        "Gambling involves risk. Please only gamble with funds that you can comfortably afford to lose. Stay Safe!"
    )
    
    await message.reply(help_text, parse_mode="HTML")


def register_help_handler(dp: Dispatcher):
    dp.register_message_handler(show_help, commands="help")

async def show_referral(message: types.Message):
    user_id = message.from_user.id
    user_data = get_user(user_id)
    if user_data is None:
        await message.reply("ℹ️ You need to start the bot first by using <b>/start</b> command.", parse_mode="HTML")
        return

    referral_code = user_data.referral_code
    referral_link = f"https://t.me/DiceNightsBot?start={referral_code}"
    referral_earnings = user_data.referral_earnings or 0.0
    invited_users = user_data.invited_users or 0

    referral_text = (
        f"Benefits:\n"
        f"• You will receive <b>{REFERRAL_REWARD_PERCENTAGE}%</b> of the playing fees of your referred players\n\n"
        f"💰 Referral earnings: <b>${referral_earnings:,.2f}</b>\n"
        f"👤 Invited users: <b>{invited_users}</b>\n\n"
        f"🔗 Your unique referral link:\n<b>{referral_link}</b>"
    )

    await message.reply(referral_text, parse_mode="HTML")

@dp.message_handler(commands=['deposit'])
async def deposit_handler(message: types.Message):
    if message.chat.type != 'private':
        await message.reply("<b>💬 Deposits can only be made in a private chat with the bot. Please message me directly.</b>", parse_mode="HTML")
        return

    keyboard = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("Litecoin", callback_data='from_currency:LTC'),
        InlineKeyboardButton("Ethereum", callback_data='from_currency:ETH'),
        InlineKeyboardButton("Bitcoin", callback_data='from_currency:BTC'),
        InlineKeyboardButton("Monero", callback_data='from_currency:XMR'),
        InlineKeyboardButton("USDT-ERC20", callback_data='from_currency:USDT'),
        InlineKeyboardButton("🔙", callback_data='back_to_start')
    )
    await message.reply('ℹ️ <b>Select the currency you want to deposit:</b>', reply_markup=keyboard, parse_mode="HTML")

async def monitor_swap_status(chat_id, order_id):
    headers = {
        'X-Requested-With': 'XMLHttpRequest'
    }
    order_url = f"{EXCHANGE_API_URL}/order"
    previous_state = None

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(order_url, params={'orderid': order_id}, headers=headers) as response:
                    if response.status != 200:
                        raise Exception(f"Unexpected response status: {response.status}")

                    order_data = await response.json()
                    order_state = order_data.get('state')
                    
                    print(f"Order {order_id}: Current state - {order_state}")

                    if order_state == previous_state:
                        await asyncio.sleep(60)
                        continue

                    previous_state = order_state

                    if order_state == 'CONFIRMING_SEND':
                        deposited_amount = float(order_data.get('to_amount', 0))
                        user_data = get_user(chat_id)
                        
                        if not user_data:
                            await bot.send_message(
                                chat_id=chat_id,
                                text="Error: Unable to retrieve your account details. Please contact support."
                            )
                            return

                        async with aiohttp.ClientSession() as session:
                            async with session.get("https://api.coinbase.com/v2/prices/LTC-USD/spot") as exchange_response:
                                if exchange_response.status != 200:
                                    raise Exception(f"Failed to fetch exchange rate: {exchange_response.status}")
                                
                                exchange_rate_data = await exchange_response.json()
                                ltc_to_usd_rate = float(exchange_rate_data.get('data', {}).get('amount', 0))

                            if ltc_to_usd_rate <= 0:
                                raise ValueError("Failed to fetch valid exchange rate.")

                        usd_amount = deposited_amount * ltc_to_usd_rate
                        usd_fee = 5
                        net_deposit = usd_amount - usd_fee

                        update_balance(chat_id, usd_amount)

                        log_message = (
                            f"🔔 <b>New deposit</b>\n\n"
                            f"User: <b>@{user_data.username} (ID: {chat_id})</b>\n"
                            f"Order ID: <b>{order_id}</b>\n"
                            f"From: <b>{order_data.get('from_currency')}</b>\n"
                            f"To: <b>{order_data.get('to_currency')}</b>\n"
                            f"Amount: <b>${usd_amount:,.2f} ({deposited_amount:.6f} LTC)</b>"
                        )
                        await bot.send_message(chat_id="-1002222833132", text=log_message, parse_mode="HTML")

                        try:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    f"Your deposit has been confirmed. Amount: <b>{format_balance(usd_amount)}</b>"
                                ),
                                parse_mode="HTML"
                            )
                        except ChatNotFound:
                            print(f"Error: Chat {chat_id} not found.")
                            return
                        break

                    elif order_state in ['FAILED', 'CANCELLED']:
                        try:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"Order <b>{order_id}</b> failed or was cancelled.",
                                parse_mode="HTML"
                            )
                        except ChatNotFound:
                            print(f"Error: Chat {chat_id} not found.")
                            return
                        
                        break

                    else:
                        await asyncio.sleep(60)

            except aiohttp.ClientError as e:
                print(f"Client error: {str(e)}")
                await asyncio.sleep(60)
            except Exception as e:
                print(f"An error occurred while checking the swap status: {str(e)}")
                break

processed_invoices = {}
invoice_locks = {}

async def monitor_ltc_status(chat_id, invoice_id):
    headers = {
        'Authorization': f'token {BTCPAY_API_KEY}',
        'Content-Type': 'application/json'
    }

    if invoice_id not in invoice_locks:
        invoice_locks[invoice_id] = asyncio.Lock()

    async with invoice_locks[invoice_id]:
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    invoice_url = f"{BTCPAY_URL}/api/v1/stores/{BTCPAY_STORE_ID}/invoices/{invoice_id}"
                    async with session.get(invoice_url, headers=headers) as response:
                        if response.status != 200:
                            raise Exception(f"Unexpected response status: {response.status}")

                        invoice_data = await response.json()
                        status = invoice_data.get('status')

                        print(f"LTC Invoice {invoice_id}: Current status - {status}")

                        if status == 'Settled':
                            if invoice_id in processed_invoices:
                                print(f"LTC Invoice {invoice_id} already processed.")
                                break

                            deposited_amount = float(invoice_data.get('amount', 0))
                            user_data = get_user(chat_id)
                            
                            if not user_data:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text="Error: Unable to retrieve your account details. Please contact support."
                                )
                                return

                            usd_fee = 5
                            net_deposit = deposited_amount - usd_fee

                            if net_deposit < 0:
                                net_deposit = 0

                            update_balance(chat_id, deposited_amount)

                            log_message = (
                                f"🔔 <b>New LTC deposit</b>\n\n"
                                f"User: <b>@{user_data.username} (ID: {chat_id})</b>\n"
                                f"Invoice ID: <b>{invoice_id}</b>\n"
                                f"Amount: <b>${deposited_amount:,.2f}</b>\n"
                            )

                            await bot.send_message(chat_id="-1002222833132", text=log_message, parse_mode="HTML")

                            try:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=(
                                            f"Your deposit has been confirmed. Amount: <b>{format_balance(deposited_amount)}</b>"
                                    ),
                                    parse_mode="HTML"
                                )
                            except ChatNotFound:
                                print(f"Error: Chat {chat_id} not found.")
                                return
                            
                            processed_invoices[invoice_id] = True
                            break

                        elif status in ['Expired', 'Invalid']:
                            try:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=f"LTC Invoice <b>{invoice_id}</b> has expired or is invalid.",
                                    parse_mode="HTML"
                                )
                            except ChatNotFound:
                                print(f"Error: Chat {chat_id} not found.")
                                return
                            
                            break

                        else:
                            await asyncio.sleep(60)

                except aiohttp.ClientError as e:
                    print(f"Client error: {str(e)}")
                    await asyncio.sleep(60)
                except Exception as e:
                    print(f"An error occurred while checking the LTC invoice status: {str(e)}")
                    break

        del invoice_locks[invoice_id]

user_last_deposit_time = {}
RATE_LIMIT_DURATION_MINUTES = 5

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("from_currency"))
async def from_currency_selection(callback_query: types.CallbackQuery):
    from_currency = callback_query.data.split(':')[1]
    to_currency = 'LTC'
    ref = EXCHANGE_ID
    user_name = callback_query.from_user.username
    user_id = callback_query.from_user.id

    now = datetime.now()

    if user_id in user_last_deposit_time:
        last_deposit_time = user_last_deposit_time[user_id]
        if (now - last_deposit_time) < timedelta(minutes=RATE_LIMIT_DURATION_MINUTES):
            remaining_time = timedelta(minutes=RATE_LIMIT_DURATION_MINUTES) - (now - last_deposit_time)
            remaining_minutes, remaining_seconds = divmod(remaining_time.total_seconds(), 60)
            await callback_query.message.edit_text(
                f"⚠️ <b>You have already made a deposit request. Please wait {int(remaining_minutes)} minutes and {int(remaining_seconds)} seconds before trying again.</b>",
                parse_mode="HTML"
            )
            return

    user_last_deposit_time[user_id] = now

    try:
        await callback_query.message.edit_text("💳 <b>Please wait while we generate your deposit address...</b>", parse_mode="HTML")

        expiration_time = now + timedelta(hours=1)
        total_seconds = int((expiration_time - now).total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_expiration_time = f"{hours:02}:{minutes:02}:{seconds:02}"

        if from_currency == 'LTC':
            invoice_data = {
                'price': 1,
                'currency': 'USD',
                'orderId': 'ltc_deposit',
                'itemDesc': 'LTC Deposit',
                'physical': False,
                'paymentCurrencies': ['LTC'],
                'buyer': {},
                'expiresAt': expiration_time.isoformat()
            }

            headers = {
                'Authorization': f'token {BTCPAY_API_KEY}',
                'Content-Type': 'application/json'
            }

            response = requests.post(f"{BTCPAY_URL}/api/v1/stores/{BTCPAY_STORE_ID}/invoices", json=invoice_data, headers=headers)
            response.raise_for_status()

            invoice_id = response.json().get('id')
            if not invoice_id:
                raise Exception('Failed to retrieve invoice ID')

            invoice_details_response = requests.get(f"{BTCPAY_URL}/api/v1/stores/{BTCPAY_STORE_ID}/invoices/{invoice_id}", headers=headers)
            invoice_details_response.raise_for_status()
            invoice_details = invoice_details_response.json()

            checkout_link = invoice_details.get('checkoutLink')
            if not checkout_link:
                raise Exception('Failed to retrieve checkout link')

            checkout_response = requests.get(checkout_link)
            checkout_response.raise_for_status()

            soup = BeautifulSoup(checkout_response.text, 'html.parser')
            script_tag = soup.find('script', text=lambda t: t and 'initialSrvModel' in t)
            if not script_tag:
                raise Exception('Failed to locate script tag with initialSrvModel')

            json_text = script_tag.string.split('initialSrvModel = ', 1)[1].split(';', 1)[0]
            srv_model_data = json.loads(json_text)
            addresss = srv_model_data.get('btcAddress')
            if not addresss:
                raise Exception('Address is empty or could not be found')

            message_text = (
                f"💳 <b>{from_currency}</b> deposit\n\n"
                "To top up your balance, transfer the desired amount to this address.\n\n"
                "<b>Please note:</b>\n"
                "<b>1. The deposit address is temporary and is only issued for 1 hour.</b>\n"
                "<b>2. One address accepts only one payment.</b>\n"
                "<b>3. Fees: 0.5%</b>\n\n"
                "Address:\n"
                f"<b>{addresss}</b>\n"
                f"Expires in: <b>{formatted_expiration_time}</b>"
            )

            await callback_query.message.edit_text(message_text, parse_mode="HTML")

            asyncio.create_task(monitor_ltc_status(callback_query.message.chat.id, invoice_id))
        
        else:
            invoice_data = {
                'price': 1,
                'currency': 'USD',
                'orderId': 'exchange_order',
                'itemDesc': 'Crypto Exchange',
                'physical': False,
                'paymentCurrencies': ['LTC'],
                'buyer': {},
                'expiresAt': expiration_time.isoformat()
            }

            headers = {
                'Authorization': f'token {BTCPAY_API_KEY}',
                'Content-Type': 'application/json'
            }

            response = requests.post(f"{BTCPAY_URL}/api/v1/stores/{BTCPAY_STORE_ID}/invoices", json=invoice_data, headers=headers)
            response.raise_for_status()

            invoice_id = response.json().get('id')
            if not invoice_id:
                raise Exception('Failed to retrieve invoice ID')

            invoice_details_response = requests.get(f"{BTCPAY_URL}/api/v1/stores/{BTCPAY_STORE_ID}/invoices/{invoice_id}", headers=headers)
            invoice_details_response.raise_for_status()
            invoice_details = invoice_details_response.json()

            checkout_link = invoice_details.get('checkoutLink')
            if not checkout_link:
                raise Exception('Failed to retrieve checkout link')

            checkout_response = requests.get(checkout_link)
            checkout_response.raise_for_status()

            soup = BeautifulSoup(checkout_response.text, 'html.parser')
            script_tag = soup.find('script', text=lambda t: t and 'initialSrvModel' in t)
            if not script_tag:
                raise Exception('Failed to locate script tag with initialSrvModel')

            json_text = script_tag.string.split('initialSrvModel = ', 1)[1].split(';', 1)[0]
            srv_model_data = json.loads(json_text)
            addresss = srv_model_data.get('btcAddress')
            if not addresss:
                raise Exception('Address is empty or could not be found')

            payload = {
                'from_currency': from_currency,
                'to_currency': to_currency,
                'to_address': addresss,
                'rate_mode': 'dynamic',
                'ref': ref
            }

            headers = {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded',
            }

            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(f"{EXCHANGE_API_URL}/create", data=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        order_id = data.get('orderid')

                        if order_id:
                            asyncio.create_task(monitor_swap_status(callback_query.message.chat.id, order_id))
                            
                            for _ in range(50):
                                async with session.get(f"{EXCHANGE_API_URL}/order", params={'orderid': order_id}) as order_resp:
                                    if order_resp.status == 200:
                                        order_data = await order_resp.json()
                                        from_address = order_data.get('from_addr')
                                        
                                        if from_address and from_address != "_GENERATING_":
                                            min_input = order_data.get('min_input', 'Unavailable')
                                            to_address = order_data.get('to_address', addresss)

                                            expiration_time = now + timedelta(hours=1)
                                            expires_in = expiration_time.strftime('%H:%M:%S')

                                            message_text = (
                                                f"💳 <b>{from_currency}</b> deposit\n\n"
                                                "To top up your balance, transfer the desired amount to this address.\n\n"
                                                "<b>Please note:</b>\n"
                                                "<b>1. The deposit address is temporary and is only issued for 1 hour. A new one will be created after that.</b>\n"
                                                "<b>2. One address accepts only one payment.</b>\n"
                                                "<b>3. Fees: 0.5%</b>\n\n"
                                                "Address:\n"
                                                f"<b>{from_address}</b>\n"
                                                f"Expires in: <b>{expires_in}</b>\n\n"
                                                f"<b>Track order:</b>\nhttps://exch.cx/order/{order_id}"
                                            )

                                            await callback_query.message.edit_text(message_text, parse_mode="HTML")
                                            break
                                    else:
                                        await asyncio.sleep(7)
                            else:
                                await callback_query.message.edit_text("ℹ️ <b>Address generation timed out. Contact support :)</b>")
                        else:
                            await callback_query.message.edit_text(f"Failed to create order: {data.get('error', 'Unknown error')}")
                    else:
                        await callback_query.message.edit_text(f"Unexpected response status...")
    except requests.RequestException as e:
        logger.error(f"HTTP request error: {e}")
        await callback_query.message.edit_text("⚠️ <b>There was an error processing your request. Please try again later.</b>")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        await callback_query.message.edit_text("⚠️ <b>An unexpected error occurred. Please contact support.</b>")

def cancel_keyboard():
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("❌ Cancel", callback_data='handle_cancel')
    )

@dp.callback_query_handler(lambda c: c.data == 'handle_cancel')
async def handle_cancel_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    delete_state(user_id)
    await callback_query.message.reply("<b>✅ Canceled. You've successfully left the withdrawal process.</b>", parse_mode="HTML")
    await callback_query.message.delete()

@dp.message_handler(commands=['withdraw'])
async def withdraw_handler(message: types.Message):
    if message.chat.type != 'private':
        await message.reply("<b>💬 Withdrawals can only be made in a private chat with the bot. Please message me directly.</b>", parse_mode="HTML")
        return

    keyboard = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("Litecoin", callback_data='withdraw_currency:LTC'),
        InlineKeyboardButton("Ethereum", callback_data='withdraw_currency:ETH'),
        InlineKeyboardButton("Bitcoin", callback_data='withdraw_currency:BTC'),
        InlineKeyboardButton("Monero", callback_data='withdraw_currency:XMR'),
        InlineKeyboardButton("USDT-ERC20", callback_data='withdraw_currency:USDT'),
        InlineKeyboardButton("🔙", callback_data='back_to_start')
    )
    await message.reply('ℹ️ <b>Select the currency you want to withdraw:</b>', reply_markup=keyboard, parse_mode="HTML")


RATE_LIMIT_DURATION_MINUTESS = 20
MAX_WITHDRAWALS_PER_DAY = 10
APPROVAL_THRESHOLD = 10

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("withdraw_currency"))
async def withdraw_currency_selection(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    selected_currency = callback_query.data.split(':')[1]

    state = load_state(user_id)
    state['withdraw_currency'] = selected_currency
    save_state(user_id, state)

    logger.info(f"User {user_id} selected currency {selected_currency}.")
    
    await callback_query.message.reply("<b>ℹ️ Please provide your withdrawal address:</b>", reply_markup=cancel_keyboard(), parse_mode="HTML")

@dp.message_handler(lambda message: load_state(message.from_user.id).get('withdraw_currency') and not load_state(message.from_user.id).get('withdraw_address'))
async def process_address(message: types.Message):
    user_id = message.from_user.id
    address = message.text.strip()

    if not address:
        await message.reply("<b>Address cannot be empty:</b>", parse_mode="HTML")
        return

    state = load_state(user_id)
    state['withdraw_address'] = address
    save_state(user_id, state)

    logger.info(f"User {user_id} provided address {address}.")

    await message.reply("<b>Please enter the amount you want to withdraw (min. 10 USD):</b>", reply_markup=cancel_keyboard(), parse_mode="HTML")
    state['awaiting_amount'] = True
    save_state(user_id, state)

    asyncio.create_task(schedule_auto_cancel(user_id))

@dp.message_handler(lambda message: is_user_withdrawing(message.from_user.id))
async def process_amount(message: types.Message):
    user_id = message.from_user.id
    amount_str = message.text.strip().replace(',', '.')

    try:
        amount = float(amount_str)
    except ValueError:
        await message.reply("<b>Invalid amount. Please enter a valid number:</b>", parse_mode="HTML")
        return

    if amount < 10:
        await message.reply("<b>Minimum withdrawal amount is 10 USD:</b>", parse_mode="HTML")
        return

    user_data = get_user(user_id)

    if user_data is None or user_data.balance < amount:
        await message.reply("<b>Insufficient balance! Please enter an amount within your available balance:</b>", parse_mode="HTML")
        return

    state = load_state(user_id)
    currency = state.get('withdraw_currency', 'LTC')
    address = state.get('withdraw_address', '')

    now = datetime.now()

    if 'last_withdrawal_time' in state:
        last_withdrawal_time = datetime.fromisoformat(state['last_withdrawal_time'])
        time_since_last_withdrawal = now - last_withdrawal_time

        if time_since_last_withdrawal < timedelta(minutes=RATE_LIMIT_DURATION_MINUTESS):
            remaining_time = timedelta(minutes=RATE_LIMIT_DURATION_MINUTESS) - time_since_last_withdrawal
            remaining_minutes, remaining_seconds = divmod(remaining_time.total_seconds(), 60)
            await message.reply(
                f"⚠️ <b>You can only withdraw once every {RATE_LIMIT_DURATION_MINUTESS} minutes. "
                f"Please wait {int(remaining_minutes)} minutes and {int(remaining_seconds)} seconds before trying again.</b>",
                parse_mode="HTML"
            )
            return

    withdrawal_dates = state.get('withdrawal_dates', [])
    withdrawal_dates = [datetime.fromisoformat(date) for date in withdrawal_dates if date]
    withdrawal_dates = [date for date in withdrawal_dates if date.date() == now.date()]

    if len(withdrawal_dates) >= MAX_WITHDRAWALS_PER_DAY:
        await message.reply(f"⚠️ <b>You have reached the daily limit of {MAX_WITHDRAWALS_PER_DAY} withdrawals.</b>", parse_mode="HTML")
        return

    if amount >= APPROVAL_THRESHOLD:
        state['requires_approval'] = True
        state['amount_pending_approval'] = amount
        state['currency_pending_approval'] = currency
        state['address_pending_approval'] = address
        save_state(user_id, state)

        await message.reply(
            f"⚠️ <b>Withdrawals over {APPROVAL_THRESHOLD} USD require approval.</b>\n"
            "Your withdrawal request has been sent for review. You will be notified once it is approved.",
            parse_mode="HTML"
        )

        await notify_admin_for_approval(user_id, amount, currency, address)

    else:
        try:
            await withdraw_crypto(user_id, amount, currency, address)
        
            state['last_withdrawal_time'] = now.isoformat()
            withdrawal_dates.append(now)
            state['withdrawal_dates'] = [date.isoformat() for date in withdrawal_dates]
            save_state(user_id, state)

        except Exception as e:
            logger.error(f"An error occurred during withdrawal: {str(e)}")
            await message.reply("An error occurred while processing your withdrawal. Please try again later.")

        delete_state(user_id)

    asyncio.create_task(schedule_auto_cancel(user_id))

def is_user_withdrawing(user_id):
    state = load_state(user_id)
    return state.get('awaiting_amount') and state.get('withdraw_currency') and state.get('withdraw_address')

async def withdraw_crypto(user_id, amount_usd, currency, address):
    try:
        headers = {
            'Authorization': f'token {BTCPAY_API_KEY}',
            'Content-Type': 'application/json'
        }

        coinbase_url = f"https://api.coinbase.com/v2/exchange-rates?currency={currency.upper()}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(coinbase_url) as resp:
                if resp.status != 200:
                    response_text = await resp.text()
                    raise Exception(f"Error fetching exchange rate (Status: {resp.status}): {response_text}")
                
                rate_data = await resp.json()
                rates = rate_data.get('data', {}).get('rates', {})
                rate = float(rates.get('USD', 0))

                if rate <= 0:
                    raise Exception(f"Invalid exchange rate received: {rate}")

        fee_percentage = 0.04
        fee_amount_usd = amount_usd * fee_percentage

        amount_usd_after_fee = amount_usd - fee_amount_usd

        amount_crypto = amount_usd_after_fee / rate

        transaction_data = {
            "destinations": [
                {
                    "destination": address,
                    "amount": str(amount_crypto),
                    "subtractFromAmount": True
                }
            ],
            "feerate": 2
        }

        transaction_url = f"{BTCPAY_URL}/api/v1/stores/{BTCPAY_STORE_ID}/payment-methods/onchain/{currency}/wallet/transactions"

        async with aiohttp.ClientSession() as session:
            async with session.post(transaction_url, json=transaction_data, headers=headers) as resp:
                if resp.status != 200:
                    response_text = await resp.text()
                    raise Exception(f"Error creating transaction (Status: {resp.status}): {response_text}")
                
                transaction_response = await resp.json()
                
                transaction_id = transaction_response.get('transactionHash')
                if not transaction_id:
                    raise Exception('Failed to retrieve transaction ID.')

        update_balance(user_id, -amount_usd)
        update_deposit_fee_profit(fee_amount_usd)

        user = await bot.get_chat_member(chat_id=user_id, user_id=user_id)
        username = user.user.username if user.user.username else "N/A"

        await bot.send_message(
            user_id, 
            f"Withdrawal of <b>{amount_crypto:.8f} {currency}</b> to <b>{address}</b> processed with transaction ID: "
            f"<b>https://live.blockcypher.com/{currency.lower()}/tx/{transaction_id}</b>",
            parse_mode="HTML"
        )

        log_message = (
            f"💸 <b>Withdrawal Processed:</b>\n\n"
            f"User: <b>@{username} (ID: {user_id})</b>\n"
            f"Amount: <b>${amount_usd:.2f} ({amount_crypto:.8f} {currency})</b>\n"
            f"Fee: <b>${fee_amount_usd:.2f}</b>\n"
            f"Address: <b>{address}</b>\n"
            f"Transaction ID: <a href='https://live.blockcypher.com/{currency.lower()}/tx/{transaction_id}'>{transaction_id}</a>"
        )

        await bot.send_message(chat_id="-1002222833132", text=log_message, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Error processing withdrawal: {e}")
        await bot.send_message(
            user_id, 
            f"<b>Looks like there was a chain error, please contact support for further information.</b>", 
            parse_mode="HTML"
        )
        
async def schedule_auto_cancel(user_id):
    await asyncio.sleep(300)
    
    state = load_state(user_id)
    if state and 'awaiting_amount' in state:
        delete_state(user_id)
        await bot.send_message(user_id, "⚠️ <b>Withdrawal process has been automatically canceled due to inactivity</b>", parse_mode="HTML")

async def notify_admin_for_approval(user_id: int, amount: float, currency: str, address: str):
    user = await bot.get_chat_member(chat_id=user_id, user_id=user_id)
    username = user.user.username if user.user.username else "N/A"
    message = (
        f"🔔 <b>Approval Required</b>\n\n"
        f"Username: @{username} <code>{user_id}</code>\n"
        f"Amount: <b>{amount} USD</b>\n"
        f"Currency: <b>{currency}</b>\n"
        f"Address: <code>{address}</code>\n\n"
        "Please review and select an option:"
    )

    keyboard = InlineKeyboardMarkup(row_width=2)
    accept_button = InlineKeyboardButton(text="✅ Accept", callback_data=f"approve_withdrawal:{user_id}:accept")
    decline_button = InlineKeyboardButton(text="❌ Decline", callback_data=f"approve_withdrawal:{user_id}:decline")
    keyboard.add(accept_button, decline_button)

    await bot.send_message("-1002304569143", message, reply_markup=keyboard, parse_mode="HTML")

    logger.info(f"Admin notified for approval of withdrawal by user {user_id}, amount: {amount} {currency}.")

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("approve_withdrawal"))
async def handle_approval(callback_query: types.CallbackQuery):
    data = callback_query.data.split(':')
    user_id = int(data[1])
    decision = data[2]

    state = load_state(user_id)

    if not state.get('requires_approval'):
        await bot.send_message(callback_query.from_user.id, "⚠️ No pending approval for this user.", parse_mode="HTML")
        return

    if decision == "accept":
        amount = state.get('amount_pending_approval')
        currency = state.get('currency_pending_approval')
        address = state.get('address_pending_approval')

        try:
            await withdraw_crypto(user_id, amount, currency, address)

            state['last_withdrawal_time'] = datetime.now().isoformat()
            withdrawal_dates = state.get('withdrawal_dates', [])
            withdrawal_dates.append(datetime.now())
            state['withdrawal_dates'] = [date.isoformat() for date in withdrawal_dates]
            save_state(user_id, state)

            delete_state(user_id)

            await bot.send_message(user_id, "✅ Your withdrawal request has been approved and processed.", parse_mode="HTML")
            await bot.send_message(callback_query.from_user.id, "Successful sent the message to user.", parse_mode="HTML")

        except Exception as e:
            logger.error(f"An error occurred during withdrawal: {str(e)}")
            await bot.send_message(callback_query.from_user.id, f"⚠️ An error occurred while processing the withdrawal: {str(e)}", parse_mode="HTML")

    elif decision == "decline":
        await bot.send_message(user_id, "❌ Your withdrawal request has been declined by the admin.", parse_mode="HTML")
        await bot.send_message(callback_query.from_user.id, "Successful sent the message to user.", parse_mode="HTML")

        delete_state(user_id)

    await callback_query.answer()

async def housebalance(message: types.Message):
    headers = {
        'Authorization': f'token {BTCPAY_API_KEY}',
        'Content-Type': 'application/json'
    }

    try:
        wallet_url = f'{BTCPAY_URL}/api/v1/stores/{BTCPAY_STORE_ID}/payment-methods/onchain/ltc/wallet'
        response = requests.get(wallet_url, headers=headers)
        response.raise_for_status()

        balance_data = response.json()
        confirmed_balance_ltc = float(balance_data.get('confirmedBalance', '0'))
        ltc_to_usd = await get_ltc_to_usd()
        balance_usd = confirmed_balance_ltc * ltc_to_usd
        hardcode_balance = 200 * ltc_to_usd
        total_balance = balance_usd + hardcode_balance

        await message.reply(f"💰 Balance available on the bot: <b>${total_balance:,.2f}</b>", parse_mode="HTML")
    
    except requests.RequestException as e:
        await message.reply(f"<b>An error occurred while fetching the balance...</b>", parse_mode="HTML")

def generate_referral_code():
    return str(uuid.uuid4())[:8]

def update_balance(user_id, amount, username=None):
    user = get_user(user_id)
    if user:
        user.balance += amount
        if username:
            user.username = username
        if not user.referral_code:
            user.referral_code = generate_referral_code()
        user.save()
    else:
        referral_code = generate_referral_code()
        user = User.create(
            id=user_id,
            balance=amount,
            username=username,
            referral_code=referral_code,
            referral_earnings=0.0,
            invited_users=0,
            timestamp=datetime.now()
        )
        user.save()

async def announce(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in auth:
        await message.reply("You are not authorized to use this command.")
        return

    if len(message.text.split(maxsplit=1)) < 2:
        await message.reply("/anno <b>your message here</b>", parse_mode="HTML")
        return

    announcement_text = message.text.split(' ', 1)[1]

    users = User.select(User.id)

    button = InlineKeyboardButton("Join us today! 🚀", url="https://t.me/DiceNight")
    keyboard = InlineKeyboardMarkup().add(button)

    success_count = 0
    failure_count = 0

    for user in users:
        try:
            await bot.send_message(user.id, announcement_text, parse_mode="HTML", reply_markup=keyboard)
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to send message to user {user.id}: {str(e)}")
            failure_count += 1

    await message.reply(
        f"📢 Announcement sent to {success_count} users. Failed to send to {failure_count} users.",
        parse_mode="HTML"
    )

def get_usd_ltc():
    try:
        response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd')
        data = response.json()
        return 1 / data['litecoin']['usd']
    except (requests.RequestException, KeyError):
        return None

def format_balance(balance):
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except locale.Error:
        pass

    formatted_balance = locale.currency(balance, grouping=True)

    if isinstance(balance, float) and balance.is_integer():
        formatted_balance = formatted_balance.replace('.00', '')

    usd_to_ltc_rate = get_usd_ltc()

    if usd_to_ltc_rate:
        ltc_amount = balance * usd_to_ltc_rate
        formatted_balance += f" ({ltc_amount:.4f} LTC)"

    return formatted_balance

auth = ["1197530278", "6089411393"]

@dp.message_handler()
async def profit_summary(message: types.Message):
    user_id = str(message.from_user.id)

    if user_id not in auth:
        await message.reply("You are not authorized to access this command.")
        return
    
    profit_data = get_profit_summary()
    summary = (
        f"<b>Profit summary:</b>\n\n"
        f"🎲 Game fees: <b>${profit_data['game_fee']}</b>\n"
        f"💸 Withdrawal fees: <b>${profit_data['deposit_fee']}</b>\n"
        f"💰 Total profit: <b>${profit_data['total_profit']}</b>"
    )
    await message.reply(summary, parse_mode="HTML")

async def view_matches(message: types.Message):
    user_id = message.from_user.id
    page = 1
    await send_matches_page(message, user_id, page, reply=True)

async def send_matches_page(message, user_id, page, reply=False):
    matches_per_page = 10
    offset = (page - 1) * matches_per_page

    total_matches = Match.select().where(
        (Match.bettor == user_id) | (Match.opponent == user_id)
    ).count()

    total_pages = max(1, ceil(total_matches / matches_per_page))

    if page < 1 or page > total_pages:
        await message.reply("Invalid page number.")
        return

    matches = Match.select().where(
        (Match.bettor == user_id) | (Match.opponent == user_id)
    ).order_by(Match.id.desc()).offset(offset).limit(matches_per_page)

    match_list = f"📆 <b>Matches History</b>\n\n"

    for idx, match in enumerate(matches):
        match_number = total_matches - offset - idx
        result_icon = "✅" if match.winner == user_id else "❌"
        date_str = match.date.strftime("%Y-%m-%d %H:%M")
        bet_amount_str = f"${match.bet_amount:.2f}"
        match_list += f"{match_number}. {result_icon} | {date_str} | Bet: {bet_amount_str}\n"

    match_list += f"\nPage: {page} / {total_pages}"

    keyboard = InlineKeyboardMarkup(row_width=2)
    if page > 1:
        prev_button = InlineKeyboardButton("⬅️ Previous", callback_data=f"matches_page:{user_id}:{page - 1}")
        keyboard.insert(prev_button)
    if page < total_pages:
        next_button = InlineKeyboardButton("Next ➡️", callback_data=f"matches_page:{user_id}:{page + 1}")
        keyboard.insert(next_button)

    if reply:
        await message.reply(match_list, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.edit_text(match_list, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("matches_page"))
async def process_matches_page(callback_query: types.CallbackQuery):
    _, user_id_str, page_str = callback_query.data.split(":")
    user_id = int(user_id_str)
    page = int(page_str)

    if callback_query.from_user.id != user_id:
        await callback_query.answer("You can't access someone else's match history.", show_alert=True)
        return

    await callback_query.answer()
    await send_matches_page(callback_query.message, user_id, page)

@dp.callback_query_handler(lambda c: c.data == 'back_to_start')
async def back_to_start(callback_query: types.CallbackQuery):
    chat_id = callback_query.from_user.id
    message_id = callback_query.message.message_id
    await bot.delete_message(chat_id=chat_id, message_id=message_id)
    await cmd_start(callback_query.message)
    await callback_query.answer()

async def on_startup(dp: Dispatcher):
    await set_commands(dp.bot)

def register_handlers(dp: Dispatcher):
    dp.register_message_handler(cmd_start, commands="start")
    dp.register_message_handler(check_balance, commands=["balance", "bal"])
    dp.register_message_handler(tip_user, commands="tip")
    dp.register_message_handler(check_bot_stats, commands="dicenightstats")
    dp.register_message_handler(show_leaderboard, commands=["leaderboard", "lb"])
    dp.register_message_handler(show_referral, commands="referral")
    dp.register_message_handler(deposit_handler, commands="deposit")
    dp.register_message_handler(view_matches, commands="matches")
    dp.register_callback_query_handler(process_matches_page, lambda c: c.data and c.data.startswith("matches_page"))
    dp.register_callback_query_handler(show_withdraw_callback, lambda c: c.data == 'show_withdraw')
    dp.register_callback_query_handler(show_deposit_callback, lambda c: c.data == 'show_deposit')
    dp.register_message_handler(withdraw_handler, commands="withdraw")
    dp.register_callback_query_handler(handle_approval, lambda c: c.data and c.data.startswith("approve_withdrawal"))
    dp.register_callback_query_handler(from_currency_selection, lambda c: c.data and c.data.startswith("from_currency"))
    dp.register_callback_query_handler(withdraw_currency_selection, lambda c: c.data and c.data.startswith("withdraw_currency"))
    dp.register_message_handler(process_address, lambda message: load_state(message.from_user.id).get('withdraw_currency') and not load_state(message.from_user.id).get('withdraw_address'))
    dp.register_message_handler(process_amount, lambda message: load_state(message.from_user.id).get('awaiting_amount'))
    dp.register_callback_query_handler(handle_cancel_callback, lambda c: c.data == 'handle_cancel') 
    dp.register_message_handler(housebalance, commands=['housebalance', 'housebal'])
    dp.register_message_handler(profit_summary, commands="profits")
    dp.register_message_handler(show_stats, commands="stats")
    dp.register_message_handler(announce, commands="anno")
    dp.register_callback_query_handler(back_to_start, lambda c: c.data == 'back_to_start')
    dp.register_callback_query_handler(trigger_deposit, lambda c: c.data == 'trigger_deposit')
    dp.register_callback_query_handler(trigger_withdraw, lambda c: c.data == 'trigger_withdraw')
    dp.register_callback_query_handler(trigger_referral, lambda c: c.data == 'trigger_referral')
    dp.register_message_handler(claim_code_handler, commands="claim")
    dp.register_message_handler(create_code_handler, commands="createcode")
    dp.register_message_handler(raffle_stats, commands="raffle")
    dp.register_callback_query_handler(raffle_buy_callback, lambda c: c.data == "raffle_buy")
    dp.register_callback_query_handler(raffle_sell_callback, lambda c: c.data == "raffle_sell")
    dp.register_message_handler(draw_raffle_winner_command, commands="draw_raffle")
    dp.register_message_handler(reset_raffle_command, commands="reset_raffle")