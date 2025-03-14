from environs import Env

# Инициализация библиотеки environs
env = Env()
env.read_env()  # Читает файл .env из корневой директории

# Чтение BOT_TOKEN и DATABASE_URL
BOT_TOKEN = env.str("BOT_TOKEN")
DATABASE_URL = env.str("DATABASE_URL", "postgresql+asyncpg://user:simplepassword@localhost:5432/telegram_parser")