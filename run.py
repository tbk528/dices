 # run.py
import sys
from db.models import db, User
from main import bot

def main(argv):
    if len(argv) == 1:
        # Start the bot
        from main import dp
        from aiogram import executor
        executor.start_polling(dp, skip_updates=True)
    else:
        command = argv[-1]
        if command == 'initdb':
            # Initialize the database
            db.connect()
            db.create_tables([User])
            db.close()
            print("Database initialized.")

if __name__ == '__main__':
    main(sys.argv)

