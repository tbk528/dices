import logging, uuid, requests, locale, asyncio, aiohttp, os, json
from datetime import datetime
from aiogram import Dispatcher, types, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.dispatcher import FSMContext
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from db.models import User, CurrentGame, ActiveBet, Match, Profits
from db.database import (
    get_user,
    update_balance,
    update_wins,
    update_losses,
    update_total_wagered,
    set_username,
    update_total_won,
    save_current_game,
    delete_current_game,
    delete_active_bet,
    save_active_bet,
    CurrentGame,
    ActiveBet,
)
from aiogram.utils import exceptions
from data.config import GAME_FEE, BOT_TOKEN, DEALER_BOT_TOKEN, REFERRAL_REWARD_PERCENTAGE

DEALER_ID = 9999

# Initialize bots
bot = Bot(token=BOT_TOKEN)
dealer_bot = Bot(token=DEALER_BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Logging configuration
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

def ensure_dealer_exists():
    dealer = get_user(DEALER_ID)
    if not dealer:
        User.create(
            id=DEALER_ID,
            username="Dealer Bot",
            balance=0,
            wins=0,
            losses=0,
            total_wagered=0.0,
            referral_code=None,
            timestamp=datetime.now()
        )

ensure_dealer_exists()

file_lock = asyncio.Lock()

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

async def update_game_fee_profit(amount: float):
    profits["game_fee"] += amount
    profits["total_profit"] += amount
    await save_profits_to_db()

async def update_deposit_fee_profit(amount: float):
    profits["deposit_fee"] += amount
    profits["total_profit"] += amount
    await save_profits_to_db()

async def update_ref_earnings(amount: float, user_id: int):
    user_data = get_user(user_id)
    if user_data and user_data.referred_by:
        logging.info(f"User {user_id} was referred by {user_data.referred_by}")
        referrer = get_user(user_data.referred_by)
        if referrer:
            reward_percentage = REFERRAL_REWARD_PERCENTAGE / 100
            reward = amount * reward_percentage
            referrer.referral_earnings = (referrer.referral_earnings or 0.0) + reward
            referrer.save()
            logging.info(f"Added reward ${reward:.2f} to referrer {referrer.username} (ID: {referrer.id})")
        else:
            logging.warning(f"Referrer with ID {user_data.referred_by} not found.")
    else:
        logging.info(f"User {user_id} was not referred by anyone.")

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

async def get_ltc_to_usd():
    async with aiohttp.ClientSession() as session:
        async with session.get('https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd') as response:
            data = await response.json()
            return data['litecoin']['usd']

async def place_soccer_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    if message.chat.type == 'private':
        await message.reply("<b>⚽ Ball</b>\n\nThis can only be played in group chats\n<b>Please join a group to play.</b>", parse_mode="HTML")
        return

    if CurrentGame.select().where((CurrentGame.bettor == user_id) | (CurrentGame.opponent == user_id)).exists() or \
       ActiveBet.select().where(ActiveBet.user_id == user_id).exists():
        await message.reply("ℹ️ <b>You are already in a game or have an active bet!</b>", parse_mode="HTML")
        return

    chat_id = str(message.chat.id)
    if len(message.text.split()) < 2:
        await message.reply(
            "⚽ <b>Ball</b>\n\n"
            "To play, type the command /ball with the desired bet amount.\n\n"
            "<b>Example:</b>\n"
            "/ball 10.50 - to play for $10.50\n"
            "/ball half - to play for half of your balance\n"
            "/ball all - to play all-in",
            parse_mode="HTML"
        )
        return

    bet_input = message.text.split()[1].strip().lower()

    user_data = get_user(user_id)
    if user_data is None:
        await message.reply("Error retrieving user data. Please try again later.")
        return

    balance = user_data.balance
    formatted_balance = format_balance(user_data.balance)

    try:
        if bet_input == "all":
            amount = balance
        elif bet_input == "half":
            amount = balance / 2
        else:
            amount = float(bet_input)
    except ValueError:
        await message.reply("Invalid amount format. Please enter a valid number or use 'all' or 'half'.")
        return

    if round(amount, 2) <= 0:
        await message.reply("Invalid bet amount. Bet amount must be greater than zero.")
        return

    if balance < amount:
        await message.reply(f"<b>❌ Not enough balance!</b>\n\nYour balance: <b>{formatted_balance}</b>", parse_mode="HTML")
        return

    set_username(user_id, username)

    # Save the active bet in the database
    save_active_bet(chat_id, user_id, amount)

    # Create keyboard for game modes
    keyboard = InlineKeyboardMarkup(row_width=1)
    best_of_3_button = InlineKeyboardButton(text="First to 3 points", callback_data=f"select_soccer_rounds:best_of_3:{user_id}")
    best_of_2_button = InlineKeyboardButton(text="First to 2 points", callback_data=f"select_soccer_rounds:best_of_2:{user_id}")
    best_of_1_button = InlineKeyboardButton(text="First to 1 point", callback_data=f"select_soccer_rounds:best_of_1:{user_id}")
    cancel_button = InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel_soccer_bet:{user_id}")
    keyboard.add(best_of_3_button, best_of_2_button, best_of_1_button, cancel_button)

    await message.reply(
        f"⚽ Choose the number of points to win",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("select_soccer_rounds"))
async def select_soccer_rounds(callback_query: types.CallbackQuery, state: FSMContext):
    _, rounds, bettor_id = callback_query.data.split(":")
    bettor_id = int(bettor_id)
    chat_id = str(callback_query.message.chat.id)

    bet_data = ActiveBet.get_or_none(chat_id=chat_id, user_id=bettor_id)
    if not bet_data:
        await callback_query.answer("This bet no longer exists.")
        return

    if bettor_id != callback_query.from_user.id:
        await callback_query.answer("You cannot select rounds for someone else's bet.")
        return

    if rounds == "best_of_1":
        required_wins = 1
    elif rounds == "best_of_2":
        required_wins = 2
    elif rounds == "best_of_3":
        required_wins = 3

    bet_data.required_wins = required_wins
    bet_data.save()

    keyboard = InlineKeyboardMarkup(row_width=2)
    accept_button = InlineKeyboardButton(text="✅ Accept Bet", callback_data=f"accept_soccer_bet:{bettor_id}")
    cancel_button = InlineKeyboardButton(text="❌ Cancel Bet", callback_data=f"cancel_soccer_bet:{bettor_id}")

    keyboard.add(accept_button)
    if 1 <= bet_data.amount <= 100:
        play_vs_bot_button = InlineKeyboardButton(text="🤖 Play vs Dealer", callback_data=f"play_vs_soccerbot:{bettor_id}")
        keyboard.add(play_vs_bot_button)
    keyboard.add(cancel_button)

    await callback_query.message.edit_text(
        f"⚽ <b>{callback_query.from_user.first_name}</b> wants to play Normal Mode!\n\n"
        f"<b>Bet:</b> ${bet_data.amount:.2f} 🔥\n"
        f"<b>Mode:</b> First to {required_wins} point{'s' if required_wins > 1 else ''}\n\n"
        "<b>Normal Mode:</b> Highest score wins.\n\n"
        'Choose to "Accept Bet" or play against the Dealer Bot.',
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("play_vs_soccerbot"))
async def play_vs_soccerbot(callback_query: types.CallbackQuery, state: FSMContext):
    _, bettor_id = callback_query.data.split(":")
    bettor_id = int(bettor_id)
    chat_id = str(callback_query.message.chat.id)

    if callback_query.from_user.id != bettor_id:
        await callback_query.answer(
            "You cannot play against the Dealer Bot on someone else's bet.",
            show_alert=True
        )
        return

    bet_data = ActiveBet.get_or_none(chat_id=chat_id, user_id=bettor_id)
    if not bet_data:
        await callback_query.answer("This bet no longer exists.")
        return

    player_data = get_user(bettor_id)
    if player_data is None or player_data.balance < bet_data.amount:
        await callback_query.answer("You don't have enough balance to play.")
        return

    update_balance(bettor_id, -bet_data.amount)

    game_id = str(uuid.uuid4())
    rolls = json.dumps({})
    round_number = 1
    bettor_wins = 0
    opponent_wins = 0
    game_mode = "normal"

    save_current_game(game_id, chat_id, bettor_id, DEALER_ID, bet_data.amount, game_mode, bet_data.required_wins, bettor_id, rolls, round_number, bettor_wins, opponent_wins, bet_mode="soccer")

    bettor_name = (await callback_query.message.chat.get_member(bettor_id)).user.first_name
    await callback_query.message.edit_text(
        f"<b>⚽ You are playing against the Dealer Bot!</b>\n\n"
        f"Player: <b>{bettor_name}</b>\n"
        f"Dealer Bot: The House\n\n"
        f"<b>{bettor_name}</b>, your turn! To start, send this emoji: ⚽",
        parse_mode="HTML"
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("accept_soccer_bet"))
async def accept_soccer_bet(callback_query: types.CallbackQuery, state: FSMContext):
    acceptor_id = callback_query.from_user.id
    bettor_id = int(callback_query.data.split(":")[1])
    chat_id = str(callback_query.message.chat.id)

    bet_data = ActiveBet.get_or_none(chat_id=chat_id, user_id=bettor_id)
    if not bet_data:
        await callback_query.answer("This bet no longer exists.")
        return

    if acceptor_id == bettor_id:
        await callback_query.answer("You cannot accept your own bet.")
        return

    if CurrentGame.select().where(CurrentGame.chat_id == chat_id, (CurrentGame.bettor == acceptor_id) | (CurrentGame.opponent == acceptor_id)).exists():
        await callback_query.answer("You or the bettor are already in an active game. Finish the current game before accepting a new bet.")
        return

    acceptor_data = get_user(acceptor_id)
    if acceptor_data is None or acceptor_data.balance < bet_data.amount:
        await callback_query.answer("You don't have enough balance to accept this bet.")
        return

    update_balance(acceptor_id, -bet_data.amount)
    update_balance(bettor_id, -bet_data.amount)

    game_id = str(uuid.uuid4())
    rolls = json.dumps({})
    round_number = 1
    bettor_wins = 0
    opponent_wins = 0
    game_mode = "normal"

    save_current_game(game_id, chat_id, bettor_id, acceptor_id, bet_data.amount, game_mode, bet_data.required_wins, bettor_id, rolls, round_number, bettor_wins, opponent_wins, bet_mode="soccer")

    bettor_name = (await callback_query.message.chat.get_member(bettor_id)).user.first_name
    await callback_query.message.edit_text(
        f"<b>⚽ Match accepted!</b>\n\n"
        f"Player 1: <b>{bettor_name}</b>\n"
        f"Player 2: <b>{callback_query.from_user.first_name}</b>\n\n"
        f"<b>{bettor_name}</b>, your turn! To start, send this emoji: ⚽",
        parse_mode="HTML"
    )

    message_link = f"https://t.me/c/{str(callback_query.message.chat.id)[4:]}/{callback_query.message.message_id}"

    await bot.send_message(
        bettor_id,
        f"⚽ Your soccer game has been [accepted]({message_link}) by {callback_query.from_user.first_name}!",
        parse_mode="Markdown",
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("cancel_soccer_bet"))
async def cancel_soccer_bet(callback_query: types.CallbackQuery):
    user_id_from_data = int(callback_query.data.split(":")[1])
    user_id_from_callback = callback_query.from_user.id
    chat_id = str(callback_query.message.chat.id)

    if user_id_from_data != user_id_from_callback:
        await callback_query.answer("You cannot cancel someone else's bet!", show_alert=True)
        return

    bet = ActiveBet.get_or_none(chat_id=chat_id, user_id=user_id_from_data)
    if bet:
        bet.delete_instance()
        await callback_query.message.edit_text("<b>❌ The bet has been successfully canceled.</b>", parse_mode="HTML")
        await callback_query.answer("You have canceled your bet.")
    else:
        await callback_query.answer("No active bet found to cancel.")

async def bot_kick(chat_id, game_id):
    game = CurrentGame.get_or_none((CurrentGame.chat_id == chat_id) & (CurrentGame.game_id == game_id))
    if not game:
        logging.info(f"No game found with game_id: {game_id}")
        return

    await asyncio.sleep(2)

    dealer_roll_message = await dealer_bot.send_dice(chat_id, emoji="⚽")
    dealer_roll_value = dealer_roll_message.dice.value
    logging.info(f"Dealer rolled a {dealer_roll_value}")

    rolls = json.loads(game.rolls)
    rolls[str(DEALER_ID)] = dealer_roll_value
    game.rolls = json.dumps(rolls)
    game.save()

    await proceed_to_next_turn_or_complete_soccer_round(None, chat_id, game_id)

async def handle_soccer_kick(message: types.Message):
    logging.info(f"Received soccer kick from user: {message.from_user.id}")

    if message.forward_from:
        return

    chat_id = str(message.chat.id)
    user_id = message.from_user.id

    game = CurrentGame.get_or_none(
        (CurrentGame.chat_id == chat_id) &
        ((CurrentGame.bettor == user_id) | (CurrentGame.opponent == user_id)) &
        (CurrentGame.turn == user_id) &
        (CurrentGame.bet_mode == "soccer")
    )

    if not game:
        return

    if message.dice.emoji != "⚽":
        return

    try:
        rolls = json.loads(game.rolls)
        if not isinstance(rolls, dict):
            rolls = {}
    except json.JSONDecodeError:
        rolls = {}

    if str(user_id) in rolls:
        await message.reply("❗ You've already kicked! Wait for your opponent's turn.", parse_mode="HTML")
        return

    roll_value = message.dice.value
    logging.info(f"User {user_id} kicked a soccer ball with value {roll_value}")
    rolls[str(user_id)] = roll_value

    game.rolls = json.dumps(rolls)
    game.save()

    if game.opponent == DEALER_ID:
        logging.info(f"Switching to Dealer Bot's turn.")
        await message.reply("🤖 <b>Dealer Bot's turn!</b> Dealer is kicking...", parse_mode="HTML")
        await bot_kick(chat_id, game.game_id)
    else:
        await proceed_to_next_turn_or_complete_soccer_round(message, chat_id, game.game_id)

async def proceed_to_next_turn_or_complete_soccer_round(message: types.Message, chat_id: str, game_id: str):
    game = CurrentGame.get_or_none((CurrentGame.chat_id == chat_id) & (CurrentGame.game_id == game_id))
    if not game:
        logging.info(f"No game found with game_id: {game_id}")
        return

    rolls = json.loads(game.rolls)

    if len(rolls) == 2:
        await complete_soccer_round(message, chat_id, game_id)
    else:
        if game.opponent != DEALER_ID:
            game.turn = game.opponent
            game.save()

            opponent_name = (await message.chat.get_member(game.opponent)).user.first_name
            await message.reply(f"<b>{opponent_name}, your turn! Send this emoji: ⚽</b>", parse_mode="HTML")

async def complete_soccer_round(message: types.Message, chat_id: str, game_id: str):
    game = CurrentGame.get_or_none((CurrentGame.chat_id == chat_id) & (CurrentGame.game_id == game_id))
    if not game:
        logging.info(f"No game found with game_id: {game_id}")
        return

    player1_id = game.bettor
    player2_id = game.opponent

    player1_name = (await bot.get_chat_member(chat_id, player1_id)).user.first_name
    player2_name = "Dealer Bot" if player2_id == DEALER_ID else (await bot.get_chat_member(chat_id, player2_id)).user.first_name

    rolls = json.loads(game.rolls)
    player1_roll = int(rolls.get(str(player1_id), 0))
    player2_roll = int(rolls.get(str(player2_id), 0))

    bot_values = [3, 4, 5, 6]
    favored_values = [4, 5, 6]

    if player2_id == DEALER_ID:
        if player2_roll in [1, 2] and player1_roll > player2_roll:
            game.bettor_wins += 1
        elif player2_roll in bot_values:
            game.opponent_wins += 1
        elif player1_roll in favored_values:
            game.bettor_wins += 1
    else:
        if player1_roll > player2_roll:
            game.bettor_wins += 1
        elif player2_roll > player1_roll:
            game.opponent_wins += 1

    game.round += 1
    game.save()

    required_wins = game.required_wins

    if game.bettor_wins >= required_wins:
        await determine_soccer_winner(message, chat_id, game_id, winner_id=player1_id)
    elif game.opponent_wins >= required_wins:
        await determine_soccer_winner(message, chat_id, game_id, winner_id=player2_id)
    else:
        game.turn = player1_id
        game.rolls = json.dumps({})
        game.save()

        await bot.send_message(
            chat_id,
            f"<b>Score:</b>\n\n"
            f"{player1_name}: {game.bettor_wins}\n"
            f"{player2_name}: {game.opponent_wins}\n\n"
            f"<b>{player1_name}</b>, your turn! Send this emoji: ⚽",
            parse_mode="HTML"
        )

async def determine_soccer_winner(message: types.Message, chat_id: str, game_id: str, winner_id=None):
    game = CurrentGame.get_or_none((CurrentGame.chat_id == chat_id) & (CurrentGame.game_id == game_id))
    if not game:
        logging.info(f"No game found with game_id: {game_id}")
        return

    player1_id = game.bettor
    player2_id = game.opponent

    player1_name = (await bot.get_chat_member(chat_id, player1_id)).user.first_name
    player2_name = "Dealer Bot" if player2_id == DEALER_ID else (await bot.get_chat_member(chat_id, player2_id)).user.first_name

    if winner_id is None:
        winner_id = player1_id if game.bettor_wins > game.opponent_wins else player2_id

    loser_id = player1_id if winner_id == player2_id else player2_id
    winner_name = player1_name if winner_id == player1_id else player2_name

    bet_amount = game.bet_amount
    total_pool = 2 * bet_amount
    fee = total_pool * GAME_FEE
    winner_earnings = total_pool - fee

    update_total_wagered(winner_id, bet_amount)
    update_total_wagered(loser_id, bet_amount)
    update_total_won(winner_id, winner_earnings)
    await update_game_fee_profit(fee)

    if loser_id == DEALER_ID:
        update_balance(DEALER_ID, -bet_amount)
        update_losses(DEALER_ID)
    else:
        update_losses(loser_id)

    update_wins(winner_id)
    update_balance(winner_id, winner_earnings)
    await update_ref_earnings(fee, winner_id)

    await bot.send_message(
        chat_id,
        f"<b>🏆 Game Over!</b>\n\n"
        f"<b>Score:</b>\n<b>{player1_name}</b> • {game.bettor_wins}\n<b>{player2_name}</b> • {game.opponent_wins}\n\n"
        f"🎉 Congratulations, <b>{winner_name}</b>! You won <b>${winner_earnings:,.2f}</b>!",
        parse_mode="HTML"
    )

    # Forward the congratulations message to another channel if the winner is not the dealer bot
    if winner_id != DEALER_ID:
        congrats_message = f"🥇<b>{winner_name}</b>! Won <b>${winner_earnings:,.2f} in Soccer ⚽</b>!"
        LOG_CHANNEL_ID = "-1002313895589"  # Replace with your desired channel ID
        await bot.send_message(chat_id=LOG_CHANNEL_ID, text=congrats_message, parse_mode="HTML")

    Match.create(
        chat_id=chat_id,
        game_id=game_id,
        bettor=player1_id,
        opponent=player2_id,
        winner=winner_id,
        bet_amount=bet_amount,
        date=datetime.now(),
        game_mode=game.game_mode,
        bettor_score=game.bettor_wins,
        opponent_score=game.opponent_wins
    )

    delete_current_game(game_id)
    delete_active_bet(chat_id, player1_id)


def generate_referral_code():
    return str(uuid.uuid4())[:8]

def update_balance(user_id, amount, username=None):
    try:
        user = get_user(user_id)

        if user:
            # Ensure the balance is a float or decimal and update it
            user.balance = max(0, user.balance + float(amount))  # Prevent negative balance

            # Update username if provided
            if username:
                user.username = str(username)

            # Assign a referral code if the user doesn't have one
            if not user.referral_code:
                user.referral_code = generate_referral_code()

            # Save the updated user data
            user.save()

        else:
            # If user doesn't exist, create a new user entry
            referral_code = generate_referral_code()
            User.create(
                id=int(user_id),  # Ensure user_id is an integer (if it's an integer field)
                balance=max(0, float(amount)),  # Ensure amount is saved as a float and prevent negative balance
                username=str(username) if username else "Unknown",  # Provide default username if none is given
                referral_code=str(referral_code),  # Ensure referral_code is a string
                timestamp=datetime.now()  # Correctly handle DateTimeField
            )

    except Exception as e:
        logging.error(f"Error updating balance for user {user_id}: {e}")

def get_usd_ltc():
    try:
        response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd')
        data = response.json()
        return 1 / data['litecoin']['usd']
    except (requests.RequestException, KeyError):
        return None

"""def format_balance(balance):
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except locale.Error:
        pass

    formatted_balance = locale.currency(balance, grouping=True)

    if isinstance(balance, float):
        formatted_balance = locale.currency(balance, grouping=True, symbol=True)
    
    usd_to_ltc_rate = get_usd_ltc()

    if usd_to_ltc_rate:
        ltc_amount = balance * usd_to_ltc_rate
        formatted_balance += f" ({ltc_amount:.4f} LTC)"

    return formatted_balance"""

def format_balance(balance):
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except locale.Error:
        pass

    if balance == 0:
        formatted_balance = locale.currency(float(balance), grouping=True, symbol=True)
    else:
        formatted_balance = locale.currency(balance, grouping=True, symbol=True)

    usd_to_ltc_rate = get_usd_ltc()

    if usd_to_ltc_rate:
        ltc_amount = balance * usd_to_ltc_rate
        formatted_balance += f" ({ltc_amount:.4f} LTC)"

    return formatted_balance

def register_handlers(dp: Dispatcher):
    dp.register_message_handler(place_soccer_bet, commands="soccer")
    dp.register_callback_query_handler(accept_soccer_bet, lambda c: c.data and c.data.startswith("accept_soccer_bet"))
    dp.register_callback_query_handler(cancel_soccer_bet, lambda c: c.data and c.data.startswith("cancel_soccer_bet"))
    dp.register_callback_query_handler(select_soccer_rounds, lambda c: c.data and c.data.startswith("select_soccer_rounds"))
    dp.register_callback_query_handler(play_vs_soccerbot, lambda c: c.data and c.data.startswith("play_vs_soccerbot"))
    dp.register_message_handler(handle_soccer_kick, content_types=types.ContentType.DICE)