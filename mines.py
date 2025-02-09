import logging
import uuid
import random
import json
import os
from datetime import datetime
from aiogram import Dispatcher, types, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils import executor
from db.models import CurrentGame, ActiveBet

# Import the database functions
from db.database import (
    get_user, update_balance, update_wins, update_losses,
    update_total_wagered, set_username, update_total_won
)

from data.config import BOT_TOKEN, ADMINS

# Initialize the Bot and Dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Constants
MINE_SYMBOL = "💣"
SAFE_SYMBOL = "✅"
HIDDEN_SYMBOL = "⬜"
CASHOUT_SYMBOL = "💰 Cash Out"

# Fixed Grid Size
FIXED_ROWS = 5
FIXED_COLS = 5

# Mines Constraints
MIN_MINES = 1
MAX_MINES = 5  # On a 5x5 grid

# Bet Constraints
MIN_BET = 1.0
MAX_BET = 100.0
DEFAULT_BET = 1.0  # Default bet if none provided

# Multiplier Table
multipliers = {
    1: {1: 0.9388, 2: .9588, 3: .9888, 4: 1.1071, 5: 1.1625},
    2: {1: 1.0109, 2: 1.0568, 3: 1.1071, 4: 1.1625, 5: 1.2237},
    3: {1: 1.0568, 2: 1.1071, 3: 1.1625, 4: 1.2237, 5: 1.2917},
    4: {1: 1.1071, 2: 1.1625, 3: 1.2237, 4: 1.2917, 5: 1.3676},
    5: {1: 1.1625, 2: 1.2237, 3: 1.2917, 4: 1.3676, 5: 1.4531},
    6: {1: 1.2237, 2: 1.2917, 3: 1.3676, 4: 1.4531, 5: 1.5500},
    7: {1: 1.2917, 2: 1.3676, 3: 1.4531, 4: 1.5500, 5: 1.6607},
    8: {1: 1.3676, 2: 1.4531, 3: 1.5500, 4: 1.6607, 5: 1.7885},
    9: {1: 1.4531, 2: 1.5500, 3: 1.6607, 4: 1.7885, 5: 1.9375},
    10: {1: 1.5500, 2: 1.6607, 3: 1.7885, 4: 1.9375, 5: 2.1136},
    11: {1: 1.6607, 2: 1.7885, 3: 1.9375, 4: 2.1136, 5: 2.3250},
    12: {1: 1.7885, 2: 1.9375, 3: 2.1136, 4: 2.3250, 5: 2.5833},
    13: {1: 1.9375, 2: 2.1136, 3: 2.3250, 4: 2.5833, 5: 2.9062},
    14: {1: 2.1136, 2: 2.3250, 3: 2.5833, 4: 2.9062, 5: 3.3214},
    15: {1: 2.3250, 2: 2.5833, 3: 2.9062, 4: 3.3214, 5: 3.8750},
    16: {1: 2.5833, 2: 2.9062, 3: 3.3214, 4: 3.8750, 5: 4.6500},
    17: {1: 2.9062, 2: 3.3214, 3: 3.8750, 4: 4.6500, 5: 5.8125},
    18: {1: 3.3214, 2: 3.8750, 3: 4.6500, 4: 5.8125, 5: 7.7500},
    19: {1: 3.8750, 2: 4.6500, 3: 5.8125, 4: 7.7500, 5: 11.6250},
    20: {1: 4.6500, 2: 5.8125, 3: 7.7500, 4: 11.6250, 5: 23.2500}
}

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("minesweeper.log"),
        logging.StreamHandler()
    ]
)

user_games = {}

# ------------------------------ #
#          Profits Tracking      #
# ------------------------------ #

PROFITS_FILE = "jsons/profits.json"

def load_profits():
    if os.path.exists(PROFITS_FILE):
        with open(PROFITS_FILE, 'r') as f:
            return json.load(f)
    else:
        return {}

def save_profits(profits_data):
    os.makedirs(os.path.dirname(PROFITS_FILE), exist_ok=True)
    with open(PROFITS_FILE, 'w') as f:
        json.dump(profits_data, f)

# ------------------------------ #
#         Helper Functions       #
# ------------------------------ #

def generate_referral_code():
    return str(uuid.uuid4())[:8]

def generate_board(rows, cols, mines):
    """
    Generates a game board with randomly placed mines.
    """
    board = [[0 for _ in range(cols)] for _ in range(rows)]
    mine_positions = random.sample(range(rows * cols), mines)
    for pos in mine_positions:
        row = pos // cols
        col = pos % cols
        board[row][col] = -1  # -1 represents a mine
    logging.debug(f"Generated board with mines at positions: {mine_positions}")
    return board

def get_multiplier(safe_hits, mines):
    """
    Retrieve the multiplier based on the number of safe hits and mines.
    """
    # Ensure safe_hits and mines are within the valid range
    max_safe_hits = max(multipliers.keys())
    if safe_hits > max_safe_hits:
        safe_hits = max_safe_hits

    min_safe_hits = min(multipliers.keys())
    if safe_hits < min_safe_hits:
        safe_hits = min_safe_hits

    max_mines = max(multipliers[safe_hits].keys())
    if mines > max_mines:
        mines = max_mines

    min_mines = min(multipliers[safe_hits].keys())
    if mines < min_mines:
        mines = min_mines

    multiplier = multipliers[safe_hits][mines]
    logging.debug(f"Multiplier for {safe_hits} safe hits and {mines} mines: {multiplier}")
    return multiplier

def format_balance(balance):
    return f"${balance:.2f}"

# ------------------------------ #
#        Keyboard Generators     #
# ------------------------------ #

def get_settings_keyboard(user_id):
    """
    Generates the inline keyboard for adjusting game settings.
    """
    game = user_games[str(user_id)]
    keyboard = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton(
            text="➕ Mines",
            callback_data=f"increase_mines:{user_id}"
        ),
        InlineKeyboardButton(
            text="➖ Mines",
            callback_data=f"decrease_mines:{user_id}"
        ),
        InlineKeyboardButton(
            text="🎮 Start Game",
            callback_data=f"start_game:{user_id}"
        ),
        InlineKeyboardButton(
            text="🔙 Back",
            callback_data=f"back_to_main:{user_id}"
        )
    ]
    keyboard.add(buttons[0], buttons[1])
    keyboard.add(buttons[2])
    return keyboard

def get_game_keyboard(user_id):
    """
    Generates the inline keyboard representing the game board with clickable cells.
    """
    game = user_games[str(user_id)]
    board = game['board']
    revealed = game['revealed']
    safe_hits = game['safe_hits']
    mines = game['mines']
    bet = game['bet']

    # Calculate current multiplier and payout
    multiplier = get_multiplier(safe_hits, mines)
    payout = bet * multiplier

    keyboard = InlineKeyboardMarkup(row_width=FIXED_COLS)
    for r in range(FIXED_ROWS):
        row_buttons = []
        for c in range(FIXED_COLS):
            if f"{r},{c}" in revealed:
                if board[r][c] == -1:
                    text = MINE_SYMBOL
                else:
                    text = SAFE_SYMBOL
            else:
                text = HIDDEN_SYMBOL
            callback_data = f"reveal:{user_id}:{r}:{c}"
            row_buttons.append(
                InlineKeyboardButton(text=text, callback_data=callback_data)
            )
        keyboard.add(*row_buttons)

    # Add Cash Out button only if the user has revealed at least one cell
    if safe_hits > 0:
        cashout_text = f"{CASHOUT_SYMBOL} (${payout:.2f})"
        keyboard.add(
            InlineKeyboardButton(
                text=cashout_text,
                callback_data=f"cash_out:{user_id}"
            )
        )
    return keyboard

# ------------------------------ #
#            Handlers            #
# ------------------------------ #

async def start_mines(message: types.Message):
    """
    Initializes a new game with fixed grid size and specified bet amount.
    Ensures only one active game per user.
    Usage: /mines [bet]
    Example: /mines 10
    """
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    user_id_str = str(user_id)
    game = user_games.get(user_id_str)

    # Fetch user from the database
    user_data = get_user(user_id)
    if user_data is None:
        # Register the user if not already registered
        set_username(user_id, username)
        user_data = get_user(user_id)
        logging.info(f"New user registered: {username} (ID: {user_id})")

    if str(user_id) in user_games:
        await message.reply("⚠️ You already have an active game. Please finish it before starting a new one.")
        logging.warning(f"User {user_id} attempted to start a new game while one is already active.")
        return
    
    if CurrentGame.select().where((CurrentGame.bettor == user_id) | (CurrentGame.opponent == user_id)).exists() or \
       ActiveBet.select().where(ActiveBet.user_id == user_id).exists():
        await message.reply("ℹ️ <b>You are already in a game or have an active bet!</b>", parse_mode="HTML")
        return

    chat_id = str(message.chat.id)
    if CurrentGame.select().where(CurrentGame.chat_id == chat_id, (CurrentGame.bettor == user_id) | (CurrentGame.opponent == user_id)).exists():
        await message.reply("ℹ️ <b>You are already in an active game!</b> Finish it before placing a new bet.", parse_mode="HTML")
        return

    # Parse the command to get bet amount
    args = message.get_args()
    if args:
        try:
            bet = float(args)
            if bet < MIN_BET or bet > MAX_BET:
                await message.reply(f"❌ Invalid bet amount. Please bet between ${MIN_BET:.2f} and ${MAX_BET:.2f}.")
                logging.warning(f"User {user_id} provided invalid bet amount: {bet}")
                return
        except ValueError:
            await message.reply("❌ Invalid bet amount. Please enter a numeric value.")
            logging.warning(f"User {user_id} provided non-numeric bet amount: {args}")
            return
    else:
        bet = DEFAULT_BET  # Use default bet if no argument provided

    userdata = get_user(user_id)

    # Check if user has sufficient balance
    if userdata.balance < bet:
        await message.reply("❌ Insufficient balance to place this bet.")
        logging.warning(f"User {user_id} has insufficient balance: ${userdata.balance:.2f} for bet: ${bet:.2f}")
        return

    # Initialize game settings
    user_games[str(user_id)] = {
        'mines': 3,         # Default number of mines
        'rows': FIXED_ROWS, # Fixed number of rows
        'cols': FIXED_COLS, # Fixed number of columns
        'balance': user_data.balance,  # Current balance
        'bet': bet,         # Set bet per game
        'board': [],
        'revealed': [],
        'safe_hits': 0      # Track the number of safe hits
    }

    logging.info(f"User {user_id} initiated a game with a bet of ${bet:.2f}.")

    keyboard = get_settings_keyboard(user_id)
    await message.reply(
        f"💣 **Minesweeper Settings**\n\n"
        f"🧨 **Mines:** {user_games[str(user_id)]['mines']}\n"
        f"🟦 **Grid Size:** {user_games[str(user_id)]['rows']}x{user_games[str(user_id)]['cols']}\n\n"
        f"💰 **Balance:** ${user_games[str(user_id)]['balance']:.2f}\n"
        f"💲 **Bet per Game:** ${user_games[str(user_id)]['bet']:.2f}\n\n"
        f"Adjust your settings and start the game!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("increase_mines"))
async def increase_mines(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_id_str = str(user_id)

    game = user_games.get(user_id_str)
    if game:
        if game['mines'] < MAX_MINES:
            game['mines'] += 1
            await callback_query.answer(f"Mines increased to {game['mines']}")
            # Update the message text to reflect the new settings
            await callback_query.message.edit_text(
                f"💣 **Minesweeper Settings**\n\n"
                f"🧨 **Mines:** {game['mines']}\n"
                f"🟦 **Grid Size:** {game['rows']}x{game['cols']}\n\n"
                f"💰 **Balance:** ${game['balance']:.2f}\n"
                f"💲 **Bet per Game:** ${game['bet']:.2f}\n\n"
                f"Adjust your settings and start the game!",
                reply_markup=get_settings_keyboard(user_id),
                parse_mode="Markdown"
            )
        else:
            await callback_query.answer(f"Maximum number of mines is {MAX_MINES}")
    else:
        await callback_query.answer("No active game found.")

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("decrease_mines"))
async def decrease_mines(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_id_str = str(user_id)

    game = user_games.get(user_id_str)
    if game:
        if game['mines'] > MIN_MINES:
            game['mines'] -= 1
            await callback_query.answer(f"Mines decreased to {game['mines']}")
            # Update the message text to reflect the new settings
            await callback_query.message.edit_text(
                f"💣 **Minesweeper Settings**\n\n"
                f"🧨 **Mines:** {game['mines']}\n"
                f"🟦 **Grid Size:** {game['rows']}x{game['cols']}\n\n"
                f"💰 **Balance:** ${game['balance']:.2f}\n"
                f"💲 **Bet per Game:** ${game['bet']:.2f}\n\n"
                f"Adjust your settings and start the game!",
                reply_markup=get_settings_keyboard(user_id),
                parse_mode="Markdown"
            )
        else:
            await callback_query.answer(f"Minimum number of mines is {MIN_MINES}")
    else:
        await callback_query.answer("No active game found.")

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("start_game"))
async def start_game(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_id_str = str(user_id)

    # Fetch user from the database
    user_data = get_user(user_id)

    game = user_games.get(user_id_str)

    if game and user_data:
        update_balance(user_id, -game['bet'])
        update_total_wagered(user_id, game['bet'])

        # Generate the game board
        game['board'] = generate_board(game['rows'], game['cols'], game['mines'])

        await callback_query.message.edit_text(
            "💣 **Minesweeper Game Started!**\n\n"
            "Click on the cells to reveal them. Avoid the mines!",
            reply_markup=get_game_keyboard(user_id),
            parse_mode="Markdown"
        )
    else:
        await callback_query.answer("Failed to start the game.")

def get_final_board_keyboard(user_id, reveal_mines=True):
    """
    Generates the inline keyboard representing the game board with all cells revealed.
    If reveal_mines is True, all mines are shown.
    """
    game = user_games[str(user_id)]
    board = game['board']
    revealed = game['revealed']
    keyboard = InlineKeyboardMarkup(row_width=FIXED_COLS)
    for r in range(FIXED_ROWS):
        row_buttons = []
        for c in range(FIXED_COLS):
            position = f"{r},{c}"
            if position in revealed or reveal_mines:
                if board[r][c] == -1:
                    text = MINE_SYMBOL
                else:
                    text = SAFE_SYMBOL
            else:
                text = HIDDEN_SYMBOL
            # Use 'noop' as callback data to prevent any action
            callback_data = 'noop'
            row_buttons.append(
                InlineKeyboardButton(text=text, callback_data=callback_data)
            )
        keyboard.add(*row_buttons)
    return keyboard

# ------------------------------ #
#            Handlers            #
# ------------------------------ #

@dp.callback_query_handler(lambda c: c.data == 'noop')
async def noop_callback(callback_query: types.CallbackQuery):
    # No operation handler for the final board buttons
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("reveal"))
async def reveal_cell(callback_query: types.CallbackQuery):
    _, user_id_str, row, col = callback_query.data.split(":")
    user_id = callback_query.from_user.id

    game = user_games.get(user_id_str)
    if not game:
        await callback_query.answer("No active game found.")
        return

    if str(user_id) != user_id_str:
        await callback_query.answer("This is not your game!")
        return

    position = f"{row},{col}"
    if position in game['revealed']:
        await callback_query.answer("You already revealed this cell.")
        return

    game['revealed'].append(position)
    row = int(row)
    col = int(col)

    if game['board'][row][col] == -1:
        # User hit a mine
        await callback_query.message.edit_text(
            "💥 **Boom! You hit a mine!**\n\n"
            "Game over.\n\n"
            "Here was the board:",
            reply_markup=get_final_board_keyboard(user_id),
            parse_mode="Markdown"
        )
        # Remove the game
        del user_games[user_id_str]
        # Update losses
        update_losses(user_id)

        # Update profits.json
        profits_data = load_profits()
        user_profits = profits_data.get(user_id_str, {'wins': 0, 'losses': 0, 'total_profit': 0.0})
        user_profits['losses'] += 1
        user_profits['total_profit'] -= game['bet']
        profits_data[user_id_str] = user_profits

        # Update house profit
        house_profits = profits_data.get('house', {'total_profit': 0.0})
        house_profits['total_profit'] += game['bet']
        profits_data['house'] = house_profits

        save_profits(profits_data)
    else:
        game['safe_hits'] += 1
        # Check if maximum safe hits reached
        max_safe_hits = max(multipliers.keys())
        if game['safe_hits'] >= max_safe_hits:
            # Automatically cash out
            await cash_out(callback_query)
        else:
            await callback_query.message.edit_reply_markup(get_game_keyboard(user_id))
            await callback_query.answer()  # No message content


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("cash_out"))
async def cash_out(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_id_str = str(user_id)

    # Fetch user from the database
    user_data = get_user(user_id)

    game = user_games.get(user_id_str)

    if game and user_data:
        # Check if the user has revealed at least one cell
        if game['safe_hits'] == 0:
            await callback_query.answer("You need to reveal at least one cell before cashing out.")
            return

        multiplier = get_multiplier(game['safe_hits'], game['mines'])
        payout = game['bet'] * multiplier

        # Calculate profit
        profit = payout - game['bet']

        # Add the payout to user's balance
        update_balance(user_id, payout)
        # Update total won
        update_total_won(user_id, payout)
        # Update wins
        update_wins(user_id)

        # Update profits.json
        profits_data = load_profits()
        user_profits = profits_data.get(user_id_str, {'wins': 0, 'losses': 0, 'total_profit': 0.0})
        user_profits['wins'] += 1
        user_profits['total_profit'] += profit
        profits_data[user_id_str] = user_profits

        # Update house profit
        house_profits = profits_data.get('house', {'total_profit': 0.0})
        house_profits['total_profit'] -= profit
        profits_data['house'] = house_profits

        save_profits(profits_data)

        await callback_query.message.edit_text(
            f"💰 **You cashed out ${payout:.2f}!**\n\n"
            f"Multiplier: x{multiplier:.4f}\n"
            f"Thanks for playing.\n\n"
            "Here was the board:",
            reply_markup=get_final_board_keyboard(user_id),
            parse_mode="Markdown"
        )
        # Remove the game
        del user_games[user_id_str]

        # Forward the cashout message and multiplier to another channel
        LOG_CHANNEL_ID = "-1002313895589"  # Replace with your desired channel ID
        user_name = callback_query.from_user.username or callback_query.from_user.first_name
        cashout_message = (
            f"🥇 **{user_name} cashed out!**\n"
            f"Multiplier: x{multiplier:.4f}\n"
            "in Minesweeper! 💣"
        )
        await bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=cashout_message,
            parse_mode="Markdown"
        )

    else:
        await callback_query.answer("Failed to cash out.")


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("back_to_main"))
async def back_to_main_menu(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_id_str = str(user_id)

    # Remove the active game
    if user_id_str in user_games:
        del user_games[user_id_str]
        await callback_query.message.edit_text("Game canceled.")
    else:
        await callback_query.answer("No active game to cancel.")

async def view_balance(message: types.Message):
    user_id = message.from_user.id

    # Fetch user from the database
    user_data = get_user(user_id)
    if user_data:
        balance = user_data.balance
        await message.reply(f"Your balance is: ${balance:.2f}")
    else:
        await message.reply("User not found.")

async def view_mineprofit(message: types.Message):
    user_id = message.from_user.id

    # Check if user is an admin
    if user_id not in ADMINS:
        await message.reply("This command is for admins only.")
        return

    profits_data = load_profits()
    house_profits = profits_data.get('house', {'total_profit': 0.0})

    total_profit = house_profits.get('total_profit', 0.0)

    if total_profit >= 0:
        profit_text = f"💰 Total Profit: ${total_profit:.2f}"
    else:
        profit_text = f"💸 Total Loss: ${-total_profit:.2f}"

    await message.reply(
        f"🏦 **House Minesweeper Profit/Loss**\n\n"
        f"{profit_text}",
        parse_mode="Markdown"
    )

def register_handlers(dp: Dispatcher):
    dp.register_message_handler(start_mines, commands=['mines'])
    dp.register_callback_query_handler(increase_mines, lambda c: c.data and c.data.startswith("increase_mines"))
    dp.register_callback_query_handler(decrease_mines, lambda c: c.data and c.data.startswith("decrease_mines"))
    dp.register_callback_query_handler(start_game, lambda c: c.data and c.data.startswith("start_game"))
    dp.register_callback_query_handler(reveal_cell, lambda c: c.data and c.data.startswith("reveal"))
    dp.register_callback_query_handler(cash_out, lambda c: c.data and c.data.startswith("cash_out"))
    dp.register_callback_query_handler(back_to_main_menu, lambda c: c.data and c.data.startswith("back_to_main"))
    dp.register_message_handler(view_balance, commands=['balance'])
    dp.register_message_handler(view_mineprofit, commands=['mineprofit'])