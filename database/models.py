from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database.db import Base  # Теперь импортируем Base напрямую из db.py

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    forward_chat_id = Column(String, unique=True, index=True)
    notification_chat_id = Column(String, nullable=True)  # Для уведомлений
    filter_enabled = Column(Boolean, default=False)  # Для фильтрации по ключевым словам

class KeywordList(Base):
    __tablename__ = "keyword_lists"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, index=True)
    name = Column(String, nullable=False)  # Название списка
    enabled = Column(Boolean, default=True)  # Включён или выключен список
    keywords = relationship("KeywordFilter", back_populates="keyword_list")

class KeywordFilter(Base):
    __tablename__ = "keyword_filters"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, index=True)
    keyword_list_id = Column(Integer, ForeignKey("keyword_lists.id"), index=True)
    keyword = Column(String, index=True)
    enabled = Column(Boolean, default=True)
    keyword_list = relationship("KeywordList", back_populates="keywords")

class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    api_id = Column(Integer)
    api_hash = Column(String)
    proxy_id = Column(Integer, nullable=True)

class Proxy(Base):
    __tablename__ = "proxies"
    id = Column(Integer, primary_key=True, index=True)
    host = Column(String)
    port = Column(Integer)
    user = Column(String)
    password = Column(String)
    type = Column(String)

class TargetChat(Base):
    __tablename__ = "target_chats"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String, unique=True, index=True)
    title = Column(String, nullable=True)