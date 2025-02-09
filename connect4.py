import logging
import random
import json
from datetime import datetime
from aiogram import Dispatcher, types, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from db.models import User, ActiveBet, CurrentGame, Match, Profits
from db.database import (
    get_user, update_balance, update_wins, update_losses,
    update_total_wagered, set_username, update_total_won,
    save_active_bet, delete_active_bet, save_current_game,
    delete_current_game
)
from data.config import GAME_FEE, BOT_TOKEN

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Constants
PLAYER1_SYMBOL = "🔴"
PLAYER2_SYMBOL = "🟡"
EMPTY_SYMBOL = "⚪"
ROWS = 6
COLUMNS = 7
user_games = {}

# Helper functions
def generate_game_id():
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))

def generate_board():
    return [[EMPTY_SYMBOL for _ in range(COLUMNS)] for _ in range(ROWS)]

def check_winner(board, symbol):
    for row in range(ROWS):
        for col in range(COLUMNS - 3):
            if all(board[row][col + i] == symbol for i in range(4)):
                return True
    for col in range(COLUMNS):
        for row in range(ROWS - 3):
            if all(board[row + i][col] == symbol for i in range(4)):
                return True
    for row in range(ROWS - 3):
        for col in range(COLUMNS - 3):
            if all(board[row + i][col + i] == symbol for i in range(4)):
                return True
    for row in range(3, ROWS):
        for col in range(COLUMNS - 3):
            if all(board[row - i][col + i] == symbol for i in range(4)):
                return True
    return False

def is_board_full(board):
    return all(cell != EMPTY_SYMBOL for row in board for cell in row)

def get_game_keyboard(game_id):
    """
    Generates the inline keyboard representing the Connect 4 board.
    """
    game = user_games.get(game_id)
    
    # Check if the game exists
    if game is None:
        logger.error(f"Game with ID {game_id} not found in user_games. Current games: {list(user_games.keys())}")
        return None

    board = game['board']
    keyboard = InlineKeyboardMarkup(row_width=COLUMNS)

    # Display the board
    for row in board:
        row_buttons = [
            InlineKeyboardButton(text=cell, callback_data='noop')
            for cell in row
        ]
        keyboard.add(*row_buttons)

    # Add buttons for each column to drop a piece
    drop_buttons = []
    for col in range(COLUMNS):
        callback_data = f"drop:{game_id}:{col}"
        drop_buttons.append(
            InlineKeyboardButton(text=str(col + 1), callback_data=callback_data)
        )
    keyboard.add(*drop_buttons)
    return keyboard


async def update_game_fee_profit(amount: float):
    profits_record, created = Profits.get_or_create(id=1)
    profits_record.game_fee += amount
    profits_record.total_profit += amount
    profits_record.last_updated = datetime.now()
    profits_record.save()

# Game Handlers
@dp.message_handler(commands=['connect4'])
async def start_connect4(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    if message.chat.type == 'private':
        await message.reply("⚠️ This game can only be played in group chats.")
        return

    user_data = get_user(user_id)
    if user_data is None:
        set_username(user_id, username)
        user_data = get_user(user_id)

    args = message.get_args()
    if not args:
        await message.reply("❌ Please specify a bet amount. Usage: /connect <bet>")
        return

    try:
        bet = float(args)
        if bet <= 0:
            raise ValueError
    except ValueError:
        await message.reply("❌ Invalid bet amount. Please enter a positive numeric value.")
        return

    if user_data.balance < bet:
        await message.reply("❌ Insufficient balance to place this bet.")
        return

    game_id = generate_game_id()
    user_games[game_id] = {
        'game_id': game_id,
        'chat_id': message.chat.id,
        'bet_amount': bet,
        'bettor': user_id,
        'opponent': None,
        'board': generate_board(),
        'current_player': None,
        'symbols': {user_id: PLAYER1_SYMBOL},
        'status': 'waiting',
    }

    save_active_bet(str(message.chat.id), user_id, bet, game_mode='connect4')
    keyboard = InlineKeyboardMarkup()
    accept_button = InlineKeyboardButton(text="✅ Accept Bet", callback_data=f"accept_connect4_bet:{user_id}:{game_id}")
    cancel_button = InlineKeyboardButton(text="❌ Cancel Bet", callback_data=f"cancel_bet:{user_id}")
    keyboard.add(accept_button, cancel_button)

    await message.reply(
        f"🎮 **Connect 4 Bet Placed!**\nPlayer: {username}\nBet Amount: ${bet:.2f}\nGame ID: `{game_id}`",
        parse_mode="Markdown", reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("accept_connect4_bet"))
async def accept_connect4_bet(callback_query: types.CallbackQuery):
    acceptor_id = callback_query.from_user.id
    _, bettor_id_str, game_id = callback_query.data.split(":")
    bettor_id = int(bettor_id_str)
    game = user_games.get(game_id)

    if not game:
        await callback_query.answer("This game no longer exists.", show_alert=True)
        return

    if game['status'] != 'waiting' or acceptor_id == bettor_id:
        await callback_query.answer("You cannot accept this bet.", show_alert=True)
        return

    acceptor_data = get_user(acceptor_id)
    if acceptor_data is None or acceptor_data.balance < game['bet_amount']:
        await callback_query.answer("❌ Insufficient balance to accept this bet.", show_alert=True)
        return

    update_balance(game['bettor'], -game['bet_amount'])
    update_balance(acceptor_id, -game['bet_amount'])
    update_total_wagered(game['bettor'], game['bet_amount'])
    update_total_wagered(acceptor_id, game['bet_amount'])

    game['opponent'] = acceptor_id
    game['symbols'][acceptor_id] = PLAYER2_SYMBOL
    game['status'] = 'active'
    game['current_player'] = game['bettor']

    save_current_game(
        game_id=game_id, chat_id=str(game['chat_id']), bettor=game['bettor'],
        opponent=game['opponent'], bet_amount=game['bet_amount'], game_mode='connect4',
        required_wins=1, turn=game['current_player'], rolls=json.dumps({}),
        round_number=1, bettor_wins=0, opponent_wins=0, bet_mode='connect4'
    )

    bettor_name = (await bot.get_chat_member(game['chat_id'], game['bettor'])).user.first_name
    acceptor_name = callback_query.from_user.first_name
    await callback_query.message.edit_text(f"✅ {acceptor_name} has accepted the bet! Starting the game.")
    await bot.send_message(
        chat_id=game['chat_id'],
        text=f"🔴 **Connect 4 Game Started!**\nPlayer 1: {bettor_name} ({PLAYER1_SYMBOL})\nPlayer 2: {acceptor_name} ({PLAYER2_SYMBOL})\nIt's {bettor_name}'s turn.",
        reply_markup=get_game_keyboard(game_id),
        parse_mode="Markdown"
    )
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("drop"))
async def drop_piece(callback_query: types.CallbackQuery):
    _, game_id, col_str = callback_query.data.split(":")
    col = int(col_str)
    user_id = callback_query.from_user.id

    # Log current game state
    logger.info(f"Attempting to drop piece in game: {game_id}. Current games: {list(user_games.keys())}")

    # Check if the game exists in user_games
    game = user_games.get(game_id)
    
    if not game:
        await callback_query.answer("The game has already ended or does not exist.", show_alert=True)
        return

    if game['status'] != 'active':
        await callback_query.answer("This game is not active.")
        return

    if user_id != game['current_player']:
        await callback_query.answer("It's not your turn.")
        return

    symbol = game['symbols'][user_id]
    board = game['board']

    # Place the piece
    for row in reversed(range(ROWS)):
        if board[row][col] == EMPTY_SYMBOL:
            board[row][col] = symbol
            break
    else:
        await callback_query.answer("This column is full.")
        return

    # Check for a winner
    if check_winner(board, symbol):
        game['status'] = 'finished'
        winner_id = user_id
        loser_id = game['opponent'] if winner_id == game['bettor'] else game['bettor']

        total_payout = game['bet_amount'] * 2
        fee = total_payout * GAME_FEE
        winner_earnings = total_payout - fee

        update_balance(winner_id, winner_earnings)
        update_total_won(winner_id, winner_earnings)
        update_wins(winner_id)
        update_losses(loser_id)
        await update_game_fee_profit(fee)

        # Record the match
        Match.create(
            chat_id=game['chat_id'],
            game_id=game_id,
            bettor=game['bettor'],
            opponent=game['opponent'],
            winner=winner_id,
            bet_amount=game['bet_amount'],
            date=datetime.now(),
            game_mode='connect4',
            bettor_score=1 if winner_id == game['bettor'] else 0,
            opponent_score=1 if winner_id == game['opponent'] else 0
        )

        # Log the removal of the game
        logger.info(f"Removing game: {game_id} from user_games.")
        delete_active_bet(str(game['chat_id']), game['bettor'])
        delete_current_game(game_id)
        user_games.pop(game_id, None)

        winner_name = (await bot.get_chat_member(game['chat_id'], winner_id)).user.first_name
        game_keyboard = get_game_keyboard(game_id)
        
        # Check if the game keyboard exists before sending it
        if game_keyboard:
            await callback_query.message.edit_text(
                f"🏆 {winner_name} wins the game! Prize: ${winner_earnings:.2f}\nFinal Board:",
                reply_markup=game_keyboard,
                parse_mode="Markdown"
            )
        else:
            logger.error(f"Failed to display final board for game ID {game_id}.")
            await callback_query.message.edit_text(
                f"🏆 {winner_name} wins the game! Prize: ${winner_earnings:.2f}\nFinal Board could not be displayed due to missing game data.",
                parse_mode="Markdown"
            )
        return


    # Check for a draw
    if is_board_full(board):
        game['status'] = 'finished'
        update_balance(game['bettor'], game['bet_amount'])
        update_balance(game['opponent'], game['bet_amount'])

        delete_active_bet(str(game['chat_id']), game['bettor'])
        delete_current_game(game_id)
        user_games.pop(game_id, None)

        await callback_query.message.edit_text(
            f"🤝 The game is a draw!\n\nFinal Board:",
            reply_markup=get_game_keyboard(game_id),
            parse_mode="Markdown"
        )
        return

    # Switch the current player
    game['current_player'] = game['opponent'] if user_id == game['bettor'] else game['bettor']

    save_current_game(
        game_id=game_id,
        chat_id=str(game['chat_id']),
        bettor=game['bettor'],
        opponent=game['opponent'],
        bet_amount=game['bet_amount'],
        game_mode='connect4',
        required_wins=1,
        turn=game['current_player'],
        rolls=json.dumps({}),
        round_number=1,
        bettor_wins=0,
        opponent_wins=0,
        bet_mode='connect4'
    )

    next_player_name = (await bot.get_chat_member(game['chat_id'], game['current_player'])).user.first_name

    await callback_query.message.edit_text(
        f"🔄 It's now {next_player_name}'s turn.",
        reply_markup=get_game_keyboard(game_id),
        parse_mode="Markdown"
    )

    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == 'noop')
async def noop_callback(callback_query: types.CallbackQuery):
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("cancel_bet"))
async def cancel_bet(callback_query: types.CallbackQuery):
    user_id_from_data = int(callback_query.data.split(":")[1])
    user_id_from_callback = callback_query.from_user.id
    chat_id = str(callback_query.message.chat.id)

    if user_id_from_data != user_id_from_callback:
        await callback_query.answer("You cannot cancel someone else's bet!", show_alert=True)
        return

    bet = ActiveBet.get_or_none(chat_id=chat_id, user_id=user_id_from_data)
    if bet:
        delete_active_bet(chat_id, user_id_from_data)
        # Find and remove the game from user_games
        for game_id, game in list(user_games.items()):
            if game['bettor'] == user_id_from_data and game['status'] == 'waiting':
                user_games.pop(game_id, None)
                break
        await callback_query.message.edit_text("<b>❌ The bet has been successfully canceled.</b>", parse_mode="HTML")
        await callback_query.answer("You have canceled your bet.")
    else:
        await callback_query.answer("No active bet found to cancel.")


@dp.message_handler(commands=['balance'])
async def view_balance(message: types.Message):
    user_id = message.from_user.id

    # Fetch user from the database
    user_data = get_user(user_id)
    if user_data:
        balance = user_data.balance
        await message.reply(f"Your balance is: ${balance:.2f}")
    else:
        await message.reply("User not found.")

def register_handlers(dp: Dispatcher):
    dp.register_message_handler(start_connect4, commands=['connect'])
    dp.register_callback_query_handler(accept_connect4_bet, lambda c: c.data and c.data.startswith("accept_connect4_bet"))
    dp.register_callback_query_handler(cancel_bet, lambda c: c.data and c.data.startswith("cancel_bet"))
    dp.register_callback_query_handler(drop_piece, lambda c: c.data and c.data.startswith("drop"))
    dp.register_callback_query_handler(noop_callback, lambda c: c.data == 'noop')
    dp.register_message_handler(view_balance, commands=['balance'])
