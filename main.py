
import logging
import logging.config
import os

from protestbot import ProtestBot

def main():

    # Create bot
    bot = ProtestBot()

    # Run bot
    dir_path = os.path.dirname(os.path.realpath(__file__))
    token_path = os.path.join(dir_path, 'bot_token.env')
    with open(token_path, 'r') as token_file:
        bot.run(token_file.read())

if __name__ == '__main__':
    dir_path = os.path.dirname(os.path.realpath(__file__))
    config_path = os.path.join(dir_path, 'logging.conf')
    logging.config.fileConfig(config_path)
    logging.info('Logger initialized.')
    main()