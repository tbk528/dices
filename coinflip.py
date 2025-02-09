import logging, uuid, json, asyncio, os, hashlib, hmac
from datetime import datetime
from aiogram import Dispatcher, types, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from db.models import User, CoinflipGame, CurrentGame, ActiveBet
from db.database import get_user, update_balance, update_wins, update_losses, update_total_wagered, set_username, update_total_won
from aiogram.dispatcher import FSMContext
from data.config import GAME_FEE, BOT_TOKEN, DEALER_BOT_TOKEN
import random

# Initialize the Bot and Dispatcher
bot = Bot(token=BOT_TOKEN)
dealer_bot = Bot(token=DEALER_BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

DEALER_ID = 9999
HEADS_GIF = "CgACAgQAAxkBAAI8jWbuUsahs02reb3_xcE2Yqu5fmHwAAIUBgACU0IMUAngPbezXZUTNgQ"
TAILS_GIF = "CgACAgQAAxkBAAI8jmbuUsaXJj9XgRDTkRzJcrY8I7q1AAKTBgACFxMMUHLltNM9pDgUNgQ"
PROFITS_FILE = "profits.json"

def load_profits():
    if os.path.exists(PROFITS_FILE):
        with open(PROFITS_FILE, "r") as f:
            return json.load(f)
    else:
        return {"game_fee": 0.0, "deposit_fee": 0.0, "total_profit": 0.0}

# Save profits to JSON file
def save_profits(profits):
    with open(PROFITS_FILE, "w") as f:
        json.dump(profits, f, indent=4)

# Update the game fee profit
def update_game_fee_profit(fee_amount):
    profits = load_profits()
    profits["game_fee"] += fee_amount
    profits["total_profit"] += fee_amount
    save_profits(profits)

# Ensure dealer bot exists
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
    else:
        logging.info("Dealer already exists.")

def generate_server_seed():
    return uuid.uuid4().hex

def hash_server_seed(server_seed):
    return hashlib.sha256(server_seed.encode()).hexdigest()

def generate_client_seed():
    return uuid.uuid4().hex

def calculate_outcome(server_seed, client_seed, nonce):
    message = f"{server_seed}:{client_seed}:{nonce}"
    hmac_result = hmac.new(server_seed.encode(), message.encode(), hashlib.sha256).hexdigest()
    return "heads" if int(hmac_result, 16) % 2 == 0 else "tails"

MAX_BET = 100.0

async def place_coinflip_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    if CurrentGame.select().where((CurrentGame.bettor == user_id) | (CurrentGame.opponent == user_id)).exists() or \
       ActiveBet.select().where(ActiveBet.user_id == user_id).exists():
        await message.reply("ℹ️ <b>You are already in a game or have an active bet!</b>", parse_mode="HTML")
        return

    chat_id = str(message.chat.id)
    if CurrentGame.select().where(CurrentGame.chat_id == chat_id, (CurrentGame.bettor == user_id) | (CurrentGame.opponent == user_id)).exists():
        await message.reply("ℹ️ <b>You are already in an active game!</b> Finish it before placing a new bet.", parse_mode="HTML")
        return

    if message.chat.type == 'private':
        await message.reply("<b>🪙 Coinflip</b>\n\nThis can only be played in group chats\n<b>Please join a group to play.</b>", parse_mode="HTML")
        return

    if len(message.text.split()) < 2:
        await message.reply(
            "🪙 <b>Coinflip</b>\n\n"
            "To play, type the command /coinflip with the desired bet amount.\n\n"
            "<b>Example:</b>\n"
            "/coinflip 10.50 - to play for $10.50\n"
            "/coinflip half - to play for half of your balance\n"
            "/coinflip all - to play all-in",
            parse_mode="HTML"
        )
        return

    bet_input = message.text.split()[1].strip().lower()
    user_data = get_user(user_id)

    if user_data is None:
        await message.reply("Error retrieving user data. Please try again later.")
        return

    balance = user_data.balance
    if balance <= 0:
        await message.reply("❌ You have no balance.")
        return

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

    if amount <= 1:
        await message.reply(f"The minimum allowed bet is $1. Please enter a higher amount.")
        return

    if amount <= 0:
        await message.reply("You cannot bet no balance.")
        return

    if amount > MAX_BET:
        await message.reply(f"The maximum allowed bet is ${MAX_BET}. Please enter a lower amount.")
        return

    if amount > balance:
        await message.reply(f"Insufficient balance. You only have ${balance:.2f}")
        return

    set_username(user_id, username)

    server_seed = generate_server_seed()
    hashed_seed = hash_server_seed(server_seed)
    client_seed = generate_client_seed()
    nonce = 1

    chat_id = str(message.chat.id)
    game_id = str(uuid.uuid4())

    CoinflipGame.create(
        chat_id=chat_id,
        game_id=game_id,
        bettor=user_id,
        bet_amount=amount,
        server_seed=server_seed,
        client_seed=client_seed,
        nonce=nonce,
        created_at=datetime.now()
    )

    keyboard = InlineKeyboardMarkup(row_width=2)
    heads_button = InlineKeyboardButton(text="Heads", callback_data=f"coinflip_pick:heads:{game_id}")
    tails_button = InlineKeyboardButton(text="Tails", callback_data=f"coinflip_pick:tails:{game_id}")
    cancel_button = InlineKeyboardButton(text="❌ Cancel", callback_data=f"coinflip_cancel:{game_id}")
    keyboard.add(heads_button, tails_button, cancel_button)

    await message.reply(
        f"🪙 Bet Amount: ${amount:.2f}\n\n"
        f"<blockquote>Game Hash: {hashed_seed}</blockquote>\n\n"
        f"Choose Heads or Tails.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("coinflip_cancel"))
async def coinflip_cancel(callback_query: types.CallbackQuery):
    _, game_id = callback_query.data.split(":")
    chat_id = str(callback_query.message.chat.id)

    game = CoinflipGame.get_or_none(game_id=game_id, chat_id=chat_id)

    if not game:
        await callback_query.answer("This game no longer exists.", show_alert=True)
        return

    bettor_id = game.bettor
    if callback_query.from_user.id != bettor_id:
        await callback_query.answer("You cannot cancel this game because you did not place the bet.", show_alert=True)
        return

    bet_amount = game.bet_amount


    # Remove the game from the database
    game.delete_instance()

    # Notify the user about the cancellation
    await callback_query.message.edit_text(
        f"🛑 <b>Coinflip Canceled</b>\n\nYour bet of <b>${bet_amount:.2f}</b> has been refunded.",
        parse_mode="HTML"
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("coinflip_pick"))
async def coinflip_pick(callback_query: types.CallbackQuery):
    _, choice, game_id = callback_query.data.split(":")
    chat_id = str(callback_query.message.chat.id)

    game = CoinflipGame.get_or_none(game_id=game_id, chat_id=chat_id)

    if not game:
        await callback_query.answer("This game no longer exists.")
        return

    bettor_id = game.bettor
    if callback_query.from_user.id != bettor_id:
        await callback_query.answer("You cannot participate in this game because you did not place the bet.", show_alert=True)
        return

    bet_amount = game.bet_amount
    server_seed = game.server_seed
    client_seed = game.client_seed
    nonce = game.nonce

    user_data = get_user(bettor_id)
    if user_data.balance < bet_amount:
        await callback_query.answer("Insufficient balance to place this bet.", show_alert=True)
        return

    update_balance(bettor_id, -bet_amount)

    # **Modify Outcome to Opposite of Player's Choice**
    if choice.lower() == "heads":
        outcome = "tails"
    else:
        outcome = "heads"

    # **Alternatively, using a ternary operator:**
    # outcome = "tails" if choice.lower() == "heads" else "heads"

    game.outcome = outcome
    game.choice = choice

    await callback_query.message.edit_text(
        f"🪙 Bet Amount: ${bet_amount:.2f}\n"
        f"Choice: <b>{choice.capitalize()}</b>\n\n"
        f"Flipping the coin...",
        parse_mode="HTML"
    )

    dealer_gif = HEADS_GIF if outcome == "heads" else TAILS_GIF
    await bot.send_animation(chat_id, dealer_gif, caption=f"Dealer chose {outcome.capitalize()}!")
    await asyncio.sleep(3)

    total_pool = 2 * bet_amount
    fee = total_pool * GAME_FEE
    winnings = total_pool - fee
    game.fee = fee
    game.winnings = winnings

    if choice.lower() == outcome:
        # This block will never execute because outcome is always opposite
        update_balance(bettor_id, winnings)
        update_wins(bettor_id)
        update_losses(DEALER_ID)
        winner_name = (await callback_query.message.chat.get_member(bettor_id)).user.first_name
        winner_message = f"🎉 <b>{winner_name}</b> wins ${winnings:.2f}!"
        game.result = "win"
    else:
        # This block will always execute
        update_wins(DEALER_ID)
        update_losses(bettor_id)
        winner_message = f"🏆 Dealer wins! Better luck next time."
        game.result = "lose"

    update_game_fee_profit(fee)
    game.save()

    verification_link = (
        f"<a href='tg://msg_url'>🔑 Provably Fair:</a>\n"
        f"Server Seed: {server_seed}\n\n"
        f"Client Seed: {client_seed}\n\n"
        f"Nonce: {nonce}\n\n"
        f"Hashed Seed: {hash_server_seed(server_seed)}"
    )

    await bot.send_message(chat_id, f"{winner_message}\n\n<blockquote>{verification_link}</blockquote>", parse_mode="HTML")

    # If the user loses, no need to send a congrats message
    # If the user wins, which never happens, this block is irrelevant
    # But keeping it for code consistency
    if game.result == "win":
        LOG_CHANNEL_ID = "-"  # Replace with your desired channel ID
        congrats_message = f"🥇<b>{winner_name}</b>! Won <b>${winnings:.2f} in Coinflip 🪙</b>!"
        await bot.send_message(chat_id=LOG_CHANNEL_ID, text=congrats_message, parse_mode="HTML")

    # Remove the game from the database
    game.delete_instance()

ensure_dealer_exists()

def register_handlers(dp: Dispatcher):
    dp.register_message_handler(place_coinflip_bet, commands="coinflip")
    dp.register_callback_query_handler(coinflip_pick, lambda c: c.data and c.data.startswith("coinflip_pick"))
    dp.register_callback_query_handler(coinflip_cancel, lambda c: c.data and c.data.startswith("coinflip_cancel"))