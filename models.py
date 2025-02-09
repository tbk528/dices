# db/models.py
from peewee import (
    SqliteDatabase, Model, IntegerField, CharField, TextField, FloatField,
    DateTimeField, BooleanField, AutoField
)
from datetime import datetime
from peewee import Model, CharField, BooleanField, ForeignKeyField, FloatField, DateTimeField
from db.database import db

db = SqliteDatabase('database.db')

class User(Model):
    id = IntegerField(primary_key=True)
    username = CharField(unique=True, null=True)
    balance = FloatField(default=0.0)
    total_wagered = FloatField(default=0.0)
    total_won = FloatField(default=0.0)
    wins = IntegerField(default=0)
    losses = IntegerField(default=0)
    slots_wins = IntegerField(default=0)
    slots_losses = IntegerField(default=0)
    referral_code = CharField(unique=True, null=True)
    referral_earnings = FloatField(default=0.0, null=False)
    invited_users = IntegerField(default=0, null=False)
    referred_by = CharField(null=True)
    timestamp = DateTimeField(default=datetime.utcnow)

    class Meta:
        database = db

class ActiveBet(Model):
    chat_id = CharField(max_length=255)
    user_id = IntegerField()
    amount = FloatField()
    timestamp = DateTimeField(default=datetime.utcnow)
    game_mode = CharField(max_length=50, null=True)
    required_wins = IntegerField(null=True)

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
    rolls = TextField()
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

class ClaimCode(Model):
    code = CharField(unique=True)  # The unique claim code
    balance = FloatField()  # Amount of balance associated with the code
    claimed = BooleanField(default=False)  # Whether the code has been claimed
    claimed_by = ForeignKeyField(User, null=True, backref='claimed_codes')  # User who claimed it (optional)
    claimed_at = DateTimeField(null=True)  # Timestamp when the code was claimed

    class Meta:
        database = db

# Connect to the database and create tables
db.connect()
db.create_tables([
    User, ActiveBet, CurrentGame, Match, Profits,
    CoinflipGame, RaffleTickets, RafflePool, ClaimCode  
], safe=True)
