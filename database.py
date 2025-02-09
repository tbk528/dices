import logging
import sqlite3
import uuid
import json
from datetime import datetime
from decimal import Decimal
from peewee import (
    Model, IntegerField, CharField, SqliteDatabase, FloatField,
    TextField, DateTimeField, BooleanField, AutoField, fn
)
from playhouse.migrate import SqliteMigrator, migrate

logger = logging.getLogger(__name__)

db = SqliteDatabase('database.db')

# Constants
TICKET_PRICE = 5.0  # Adjust as needed
FREE_TICKET_THRESHOLD = 200.0  # Adjust as needed

# Define your models (users, bets, games, raffles, etc.)
class User(Model):
    id = IntegerField(primary_key=True)
    username = CharField(unique=True, null=True)
    balance = FloatField(default=0.0)
    wins = IntegerField(default=0)
    losses = IntegerField(default=0)
    total_wagered = FloatField(default=0.0)  # Changed to FloatField
    total_won = FloatField(default=0.0)  # Changed to FloatField
    referral_code = CharField(unique=True, null=True)
    referral_earnings = FloatField(default=0.0, null=False)
    invited_users = IntegerField(default=0, null=False)
    referred_by = CharField(null=True)
    slots_wins = IntegerField(default=0)
    slots_losses = IntegerField(default=0)
    timestamp = DateTimeField(default=datetime.utcnow)  # Added timestamp

    class Meta:
        database = db

class ActiveBet(Model):
    chat_id = CharField(max_length=255)
    user_id = IntegerField()
    amount = FloatField()
    timestamp = DateTimeField(default=datetime.utcnow)
    game_mode = CharField(max_length=50, null=True)
    required_wins = IntegerField(null=True)
    game_id = CharField(null=True) 

    class Meta:
        database = db

class CurrentGame(Model):
    game_id = CharField(max_length=255, unique=True)
    chat_id = CharField(max_length=255)
    bettor = IntegerField()
    opponent = IntegerField()
    bet_amount = FloatField()
    game_mode = CharField(max_length=50)
    bet_mode = CharField(default="dice")
    required_wins = IntegerField()
    turn = IntegerField()
    rolls = TextField()  # Store as JSON string
    round = IntegerField(default=1)
    bettor_wins = IntegerField(default=0)
    opponent_wins = IntegerField(default=0)
    start_time = DateTimeField(default=datetime.utcnow)
    is_complete = BooleanField(default=False)

    class Meta:
        database = db

class Match(Model):
    id = AutoField()
    chat_id = CharField()
    game_id = CharField()
    bettor = IntegerField()
    opponent = IntegerField()
    winner = IntegerField()
    bet_amount = FloatField()
    date = DateTimeField()
    game_mode = CharField()
    bettor_score = IntegerField()
    opponent_score = IntegerField()

    class Meta:
        database = db

class Profits(Model):
    id = AutoField()
    game_fee = FloatField(default=0.0)
    deposit_fee = FloatField(default=0.0)
    total_profit = FloatField(default=0.0)
    last_updated = DateTimeField(default=datetime.utcnow)

    class Meta:
        database = db

class CoinflipGame(Model):
    id = AutoField()
    chat_id = CharField(max_length=255)
    game_id = CharField(max_length=255, unique=True)
    bettor = IntegerField()
    bet_amount = FloatField()
    server_seed = CharField(max_length=64)
    client_seed = CharField(max_length=64)
    nonce = IntegerField()
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        database = db

# Updated RaffleTickets Model
class RaffleTickets(Model):
    id = AutoField()
    user_id = IntegerField(unique=True)  # Added unique constraint
    tickets = IntegerField(default=0)
    earned_by_wagering = IntegerField(default=0)  # Changed to IntegerField
    timestamp = DateTimeField(default=datetime.utcnow)

    class Meta:
        database = db

class RafflePool(Model):
    id = AutoField()
    total_tickets = IntegerField(default=0)
    total_pool = FloatField(default=0.0)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        database = db

# Connect to the database and create tables
db.connect()
db.create_tables([
    User, ActiveBet, CurrentGame, Match, Profits,
    CoinflipGame, RaffleTickets, RafflePool
], safe=True)

# Migration function to add new columns/tables if needed
def migrate_database():
    migrator = SqliteMigrator(db)
    try:
        with db.atomic():
            # Add unique constraint and change field type
            migrate(
                migrator.drop_column('raffletickets', 'earned_by_wagering'),  # Drop old column if exists
                migrator.add_column('raffletickets', 'earned_by_wagering', IntegerField(default=0)),
                migrator.drop_index('raffletickets', 'raffletickets_user_id'),  # Drop old index if exists
                migrator.add_index('raffletickets', ('user_id',), unique=True)
            )
        print("Migration applied: Updated 'RaffleTickets' table.")
    except Exception as e:
        print(f"No migration applied or already up-to-date: {e}")

# Call migration function to ensure schema is up-to-date
migrate_database()

# Helper functions and your existing functions...
def get_user(user_id):
    try:
        user = User.get(User.id == user_id)
        if not user.referral_code:
            user.referral_code = str(uuid.uuid4())[:8]  # Generate a unique referral code
            user.save()
        return user
    except User.DoesNotExist:
        logger.error(f"User {user_id} does not exist.")
        return None
    except Exception as e:
        logger.error(f"An error occurred while fetching user {user_id}: {e}")
        return None

def update_balance(user_id, amount, username=None):
    amount = round(float(amount), 2)

    user = get_user(user_id)
    
    if user:
        user.balance = round(float(user.balance) + amount, 2)

        if username:
            user.username = username
        user.save()
    else:
        user = User.create(
            id=user_id,
            balance=round(amount, 2),
            username=username
        )
        user.save()

def update_slots_wins(user_id, amount_won):
    user = get_user(user_id)
    if user:
        user.slots_wins += amount_won
        user.save()

def update_slots_losses(user_id, amount_lost):
    user = get_user(user_id)
    if user:
        user.slots_losses += amount_lost
        user.save()

def update_wins(user_id):
    user = get_user(user_id)
    if user:
        user.wins += 1
        user.save()

def update_losses(user_id):
    user = get_user(user_id)
    if user:
        user.losses += 1
        user.save()

# Update total wagered and give free raffle tickets
def update_total_wagered(user_id, wagered_amount):
    user = get_user(user_id)
    if user:
        user.total_wagered += wagered_amount
        user.save()

        # Calculate total free tickets earned based on total wagered
        total_free_tickets_earned = int(user.total_wagered // FREE_TICKET_THRESHOLD)

        # Get or create the user's raffle tickets record
        user_tickets = get_user_raffle_tickets(user_id)

        # Calculate new free tickets to award
        new_free_tickets = total_free_tickets_earned - user_tickets.earned_by_wagering

        if new_free_tickets > 0:
            user_tickets.tickets += new_free_tickets
            user_tickets.earned_by_wagering = total_free_tickets_earned
            user_tickets.save()
            logger.info(f"User {user_id} earned {new_free_tickets} free raffle tickets by wagering.")

def update_total_won(user_id, won_amount):
    user = get_user(user_id)
    if user:
        user.total_won += won_amount
        user.save()

def set_username(user_id, username):
    user = get_user(user_id)
    if user:
        user.username = username
        user.save()

def get_leaderboard_data():
    logger.info("Attempting to fetch leaderboard data from the database.")
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, username, total_wagered, wins, losses 
            FROM user 
            ORDER BY total_wagered DESC 
            LIMIT 10
        ''')
        leaderboard_data = cursor.fetchall()
        conn.close()

        if not leaderboard_data:
            logger.info("No data found in the leaderboard.")
            return []

        formatted_data = [{"user_id": user[0], "username": user[1], "total_wagered": user[2], "wins": user[3], "losses": user[4]} for user in leaderboard_data]
        logger.info("Successfully fetched and formatted leaderboard data.")
        return formatted_data
    except Exception as e:
        logger.error(f"Error while fetching leaderboard data: {e}")
        return []

def get_user_by_username(username):
    try:
        return User.get(User.username == username)
    except User.DoesNotExist:
        return None

def add_referral(referrer_id, referred_id):
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO referrals (referrer_id, referred_id) 
            VALUES (?, ?)
        ''', (referrer_id, referred_id))
        conn.commit()
        conn.close()
        logger.info(f"Referral added: referrer_id={referrer_id}, referred_id={referred_id}")
    except Exception as e:
        logger.error(f"Error adding referral: {e}")

def get_referral_data(user_id):
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as referred_count, SUM(referral_earnings) as referral_earnings 
            FROM referrals 
            WHERE referrer_id = ?
        ''', (user_id,))
        referral_data = cursor.fetchone()
        conn.close()

        if referral_data:
            return {
                "referred_count": referral_data[0] or 0,
                "referral_earnings": referral_data[1] or 0.0
            }
        else:
            return {
                "referred_count": 0,
                "referral_earnings": 0.0
            }
    except Exception as e:
        logger.error(f"Error while fetching referral data: {e}")
        return {
            "referred_count": 0,
            "referral_earnings": 0.0
        }

def get_active_bets(chat_id):
    return list(ActiveBet.select().where(ActiveBet.chat_id == str(chat_id)))

def get_current_games(chat_id):
    return list(CurrentGame.select().where(CurrentGame.chat_id == str(chat_id)))

def is_user_in_current_game(user_id):
    return CurrentGame.select().where((CurrentGame.bettor == user_id) | (CurrentGame.opponent == user_id)).exists()

def is_user_in_active_bet(user_id):
    return ActiveBet.select().where(ActiveBet.user_id == user_id).exists()

def save_active_bet(chat_id, user_id, amount, game_mode=None, required_wins=None):
    bet, created = ActiveBet.get_or_create(
        chat_id=str(chat_id),
        user_id=user_id,
        defaults={'amount': amount, 'game_mode': game_mode, 'required_wins': required_wins}
    )
    if not created:
        bet.amount = amount
        bet.game_mode = game_mode
        bet.required_wins = required_wins
        bet.save()

def delete_active_bet(chat_id, user_id):
    query = ActiveBet.delete().where((ActiveBet.chat_id == str(chat_id)) & (ActiveBet.user_id == user_id))
    query.execute()

def save_current_game(game_id, chat_id, bettor, opponent, bet_amount, game_mode, required_wins, turn, rolls, round_number, bettor_wins, opponent_wins, bet_mode):
    game, created = CurrentGame.get_or_create(
        game_id=game_id,
        defaults={
            'chat_id': str(chat_id),
            'bettor': bettor,
            'opponent': opponent,
            'bet_amount': bet_amount,
            'game_mode': game_mode,
            'required_wins': required_wins,
            'turn': turn,
            'rolls': json.dumps(rolls),  # Serialize rolls to JSON
            'round': round_number,
            'bettor_wins': bettor_wins,
            'opponent_wins': opponent_wins,
            'bet_mode': bet_mode
        }
    )
    if not created:
        game.chat_id = str(chat_id)
        game.bettor = bettor
        game.opponent = opponent
        game.bet_amount = bet_amount
        game.game_mode = game_mode
        game.required_wins = required_wins
        game.turn = turn
        game.rolls = json.dumps(rolls)  # Serialize rolls to JSON
        game.round = round_number
        game.bettor_wins = bettor_wins
        game.opponent_wins = opponent_wins
        game.bet_mode = bet_mode
        game.save()

def delete_current_game(game_id):
    query = CurrentGame.delete().where(CurrentGame.game_id == game_id)
    query.execute()

def add_referral_code_column():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Check if the referral_code column already exists to avoid errors
    cursor.execute("PRAGMA table_info(user)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'referral_code' not in columns:
        # Add the referral_code column to the users table
        cursor.execute('ALTER TABLE user ADD COLUMN referral_code TEXT')
        print("Column 'referral_code' added to 'user' table.")
    else:
        print("Column 'referral_code' already exists in 'user' table.")

    conn.commit()
    conn.close()

# Raffle-related functions
def get_raffle_pool():
    raffle_pool, created = RafflePool.get_or_create(
        id=1,
        defaults={'total_tickets': 0, 'total_pool': 0.0, 'created_at': datetime.utcnow(), 'updated_at': datetime.utcnow()}
    )
    return raffle_pool

def get_user_raffle_tickets(user_id):
    user_tickets, created = RaffleTickets.get_or_create(
        user_id=user_id,
        defaults={'tickets': 0, 'earned_by_wagering': 0}
    )
    return user_tickets

def purchase_raffle_ticket(user_id, num_tickets=1):
    try:
        user = get_user(user_id)
        raffle_pool = get_raffle_pool()

        # Deduct the cost from user's balance
        ticket_cost = TICKET_PRICE * num_tickets
        if user.balance < ticket_cost:
            return False, "Insufficient balance."

        user.balance -= ticket_cost
        user.save()

        # Add raffle tickets for the user
        user_tickets = get_user_raffle_tickets(user_id)
        user_tickets.tickets += num_tickets
        user_tickets.save()

        # Update raffle pool
        raffle_pool.total_tickets += num_tickets
        raffle_pool.total_pool += ticket_cost
        raffle_pool.updated_at = datetime.utcnow()
        raffle_pool.save()

        return True, f"You purchased {num_tickets} ticket(s)."

    except Exception as e:
        logger.error(f"Error purchasing raffle tickets: {e}")
        return False, "An error occurred."

def track_wagering_and_award_ticket(user_id, amount_wagered):
    try:
        user = get_user(user_id)
        raffle_pool = get_raffle_pool()

        # Update user's total wagered amount
        user.total_wagered += amount_wagered
        user.save()

        # Award free raffle tickets based on total wagered
        total_free_tickets_earned = int(user.total_wagered // FREE_TICKET_THRESHOLD)
        user_tickets = get_user_raffle_tickets(user_id)

        # Calculate new free tickets to award
        new_free_tickets = total_free_tickets_earned - user_tickets.earned_by_wagering

        if new_free_tickets > 0:
            user_tickets.tickets += new_free_tickets
            user_tickets.earned_by_wagering = total_free_tickets_earned
            user_tickets.save()

            # Update raffle pool
            raffle_pool.total_tickets += new_free_tickets
            raffle_pool.updated_at = datetime.utcnow()
            raffle_pool.save()

            logger.info(f"User {user_id} earned {new_free_tickets} free raffle ticket(s).")
            return True, f"Congrats! You earned {new_free_tickets} free ticket(s)."
        return False, "No free tickets earned."

    except Exception as e:
        logger.error(f"Error awarding raffle tickets: {e}")
        return False, "An error occurred."

def draw_raffle_winner():
    try:
        raffle_pool = get_raffle_pool()
        if raffle_pool.total_tickets == 0:
            return None, "No tickets sold."

        # Retrieve all tickets
        tickets = list(RaffleTickets.select())
        total_tickets = sum(ticket.tickets for ticket in tickets)

        import random
        random_ticket_number = random.randint(1, total_tickets)

        current_sum = 0
        for ticket in tickets:
            current_sum += ticket.tickets
            if current_sum >= random_ticket_number:
                winner_user_id = ticket.user_id
                return winner_user_id, f"User {winner_user_id} wins the raffle!"

    except Exception as e:
        logger.error(f"Error drawing raffle winner: {e}")
        return None, "An error occurred."
