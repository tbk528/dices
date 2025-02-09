


import json
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils import executor
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.middlewares import BaseMiddleware
from bot.general import dp, raffle_stats, raffle_buy_callback, raffle_sell_callback, draw_raffle_winner_command, reset_raffle_command, claim_code_handler, create_code_handler, check_bot_stats, cmd_start, trigger_deposit, trigger_withdraw, check_balance, show_stats, show_leaderboard, tip_user, register_help_handler, show_referral, deposit_handler, withdraw_handler, from_currency_selection, withdraw_currency_selection, process_address, process_amount, housebalance, profit_summary, on_startup, handle_cancel_callback, handle_approval, trigger_referral, announce, view_matches, process_matches_page
from bot.dice import cancel_bet, place_bet, handle_dice_roll, accept_bet, select_game_mode, select_rounds, play_vs_dealer
from bot.slots import start_slots, adjust_bet, double_bet, set_bet, spin_slot_machine, back_to_slots_menu, show_slots_stats
from bot.bask import place_basket_bet, select_basket_rounds, accept_basket_bet, cancel_basket_bet, handle_basketball_shot, play_vs_basketbot
from bot.darts import place_dart_bet, accept_dart_bet, cancel_dart_bet, handle_dart_throw, select_dart_rounds, play_vs_dartbot
from bot.soccer import place_soccer_bet, accept_soccer_bet, cancel_soccer_bet, select_soccer_rounds, handle_soccer_kick, play_vs_soccerbot
from bot.bowling import place_bowling_bet, accept_bowling_bet, cancel_bowling_bet, select_bowling_rounds, handle_bowling_roll, play_vs_bowlingbot
from bot.mines import view_balance, decrease_mines, increase_mines, start_mines, start_game, reveal_cell, back_to_main_menu, cash_out, view_mineprofit
from bot.coinflip import coinflip_pick, place_coinflip_bet, coinflip_cancel
from bot.connect4 import start_connect4, accept_connect4_bet, drop_piece, noop_callback

API_TOKEN = '7876444708:AAGcguVPDP4zvTsx1ecYHQn6XbHQvUmY61M'

ALLOWED_GROUP = ["", "", "","", "", ""]

class GroupRestrictionMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        if message.chat.type == 'private' or str(message.chat.id) in ALLOWED_GROUP:
            return
        else:
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        if callback_query.message.chat.type == 'private' or str(callback_query.message.chat.id) in ALLOWED_GROUP:
            return
        else:
            raise CancelHandler()

def load_state(user_id):
    try:
        with open("jsons/state.json", 'r') as file:
            states = json.load(file)
    except FileNotFoundError:
        states = {}
    return states.get(str(user_id), {})

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())
dp.middleware.setup(GroupRestrictionMiddleware())

async def show_deposit_callback(callback_query: types.CallbackQuery):
    chat_id = callback_query.from_user.id
    message_id = callback_query.message.message_id
    await bot.delete_message(chat_id=chat_id, message_id=message_id)
    await deposit_handler(callback_query.message)
    await callback_query.answer()

async def show_withdraw_callback(callback_query: types.CallbackQuery):
    chat_id = callback_query.from_user.id
    message_id = callback_query.message.message_id
    await bot.delete_message(chat_id=chat_id, message_id=message_id)
    await withdraw_handler(callback_query.message)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == 'back_to_start')
async def back_to_start(callback_query: types.CallbackQuery):
    chat_id = callback_query.from_user.id
    message_id = callback_query.message.message_id
    await bot.delete_message(chat_id=chat_id, message_id=message_id)
    await cmd_start(callback_query.message)
    await callback_query.answer()

@dp.message_handler(content_types=types.ContentType.DICE)
async def handle_emoji_games(message: types.Message):
    if message.dice.emoji == "🎲":
        await handle_dice_roll(message)
    elif message.dice.emoji == "🎯":
        await handle_dart_throw(message)
    elif message.dice.emoji == "🏀":
        await handle_basketball_shot(message)
    elif message.dice.emoji == "⚽":
        await handle_soccer_kick(message)
    elif message.dice.emoji == "🎳":
        await handle_bowling_roll(message)

####################### GENERAL
dp.register_message_handler(cmd_start, commands="start")
dp.register_message_handler(check_balance, commands=["balance", "bal"])
dp.register_message_handler(tip_user, commands="tip")
dp.register_message_handler(check_bot_stats, commands="dicenightstats")
dp.register_message_handler(show_leaderboard, commands=["leaderboard", "lb"])
dp.register_message_handler(show_referral, commands="referral")
dp.register_message_handler(deposit_handler, commands="deposit")
dp.register_callback_query_handler(show_withdraw_callback, lambda c: c.data == 'show_withdraw')
dp.register_callback_query_handler(show_deposit_callback, lambda c: c.data == 'show_deposit')
dp.register_message_handler(withdraw_handler, commands="withdraw")
dp.register_callback_query_handler(from_currency_selection, lambda c: c.data and c.data.startswith("from_currency"))
dp.register_callback_query_handler(handle_approval, lambda c: c.data and c.data.startswith("approve_withdrawal"))
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
dp.register_message_handler(view_matches, commands="matches")
dp.register_callback_query_handler(process_matches_page, lambda c: c.data and c.data.startswith("matches_page"))
dp.register_message_handler(claim_code_handler, commands="claim") 
dp.register_message_handler(create_code_handler, commands="createcode")
dp.register_message_handler(raffle_stats, commands="raffle") 
dp.register_callback_query_handler(raffle_buy_callback, lambda c: c.data == "raffle_buy")
dp.register_callback_query_handler(raffle_sell_callback, lambda c: c.data == "raffle_sell")
dp.register_message_handler(draw_raffle_winner_command, commands="draw_raffle")
dp.register_message_handler(reset_raffle_command, commands="reset_raffle")
####################### DICE
dp.register_message_handler(place_bet, commands="dice")
dp.register_callback_query_handler(accept_bet, lambda c: c.data and c.data.startswith("accept_bet"))
dp.register_callback_query_handler(cancel_bet, lambda c: c.data and c.data.startswith("cancel_bet"))
dp.register_callback_query_handler(select_game_mode, lambda c: c.data and c.data.startswith("select_mode"))
dp.register_callback_query_handler(select_rounds, lambda c: c.data and c.data.startswith("select_rounds"))
dp.register_callback_query_handler(play_vs_dealer, lambda c: c.data and c.data.startswith("play_vs_dealer"))
####################### SLOTS
####################### BASKETBALL
dp.register_message_handler(place_basket_bet, commands="bask")
dp.register_callback_query_handler(select_basket_rounds, lambda c: c.data and c.data.startswith("select_basket_rounds"))
dp.register_callback_query_handler(accept_basket_bet, lambda c: c.data and c.data.startswith("accept_basket_bet"))
dp.register_callback_query_handler(cancel_basket_bet, lambda c: c.data and c.data.startswith("cancel_basket_bet"))
dp.register_callback_query_handler(play_vs_basketbot, lambda c: c.data and c.data.startswith("play_vs_basketbot"))
####################### DARTS
dp.register_message_handler(place_dart_bet, commands="darts")
dp.register_callback_query_handler(accept_dart_bet, lambda c: c.data and c.data.startswith("accept_dart_bet"))
dp.register_callback_query_handler(cancel_dart_bet, lambda c: c.data and c.data.startswith("cancel_dart_bet"))
dp.register_callback_query_handler(select_dart_rounds, lambda c: c.data and c.data.startswith("select_dart_rounds"))
dp.register_callback_query_handler(play_vs_dartbot, lambda c: c.data and c.data.startswith("play_vs_dartbot"))
####################### SOCCER
dp.register_message_handler(place_soccer_bet, commands="ball")
dp.register_callback_query_handler(accept_soccer_bet, lambda c: c.data and c.data.startswith("accept_soccer_bet"))
dp.register_callback_query_handler(cancel_soccer_bet, lambda c: c.data and c.data.startswith("cancel_soccer_bet"))
dp.register_callback_query_handler(select_soccer_rounds, lambda c: c.data and c.data.startswith("select_soccer_rounds"))
dp.register_callback_query_handler(play_vs_soccerbot, lambda c: c.data and c.data.startswith("play_vs_soccerbot"))
###################### BOWLING
dp.register_message_handler(place_bowling_bet, commands="bowl")
dp.register_callback_query_handler(accept_bowling_bet, lambda c: c.data and c.data.startswith("accept_bowling_bet"))
dp.register_callback_query_handler(cancel_bowling_bet, lambda c: c.data and c.data.startswith("cancel_bowling_bet"))
dp.register_callback_query_handler(select_bowling_rounds, lambda c: c.data and c.data.startswith("select_bowling_rounds"))
dp.register_callback_query_handler(play_vs_bowlingbot, lambda c: c.data and c.data.startswith("play_vs_bowlingbot"))
###################### MINES
dp.register_message_handler(start_mines, commands=['mines'])
dp.register_callback_query_handler(increase_mines, lambda c: c.data and c.data.startswith("increase_mines"))
dp.register_callback_query_handler(decrease_mines, lambda c: c.data and c.data.startswith("decrease_mines"))
dp.register_callback_query_handler(start_game, lambda c: c.data and c.data.startswith("start_game"))
dp.register_callback_query_handler(reveal_cell, lambda c: c.data and c.data.startswith("reveal"))
dp.register_callback_query_handler(cash_out, lambda c: c.data and c.data.startswith("cash_out"))
dp.register_callback_query_handler(back_to_main_menu, lambda c: c.data and c.data.startswith("back_to_main"))
dp.register_message_handler(view_balance, commands=['balance'])
dp.register_message_handler(view_mineprofit, commands=['mineprofit'])
###################### COINFLIP
dp.register_callback_query_handler(coinflip_pick, lambda c: c.data and c.data.startswith("coinflip_pick"))
dp.register_callback_query_handler(coinflip_cancel, lambda c: c.data and c.data.startswith("coinflip_cancel"))
###################### CONNECT4
dp.register_message_handler(start_connect4, commands=['connect'])
dp.register_callback_query_handler(accept_connect4_bet, lambda c: c.data and c.data.startswith("accept_connect4_bet"))
dp.register_callback_query_handler(cancel_bet, lambda c: c.data and c.data.startswith("cancel_bet"))
dp.register_callback_query_handler(drop_piece, lambda c: c.data and c.data.startswith("drop"))
dp.register_callback_query_handler(noop_callback, lambda c: c.data == 'noop')
dp.register_message_handler(view_balance, commands=['balance'])
register_help_handler(dp)

if __name__ == '__main__':
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
