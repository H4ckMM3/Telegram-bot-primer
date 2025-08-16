from datetime import datetime, timezone, time, timedelta
from enum import Enum as PyEnum
from sqlalchemy import (
    Integer, String, Boolean, DateTime, Time, 
    ForeignKey, UniqueConstraint, Index, Enum,
    Column, create_engine, MetaData
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func

engine = create_engine('sqlite:///habits.db')
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def init_db():
    Base.metadata.create_all(engine)

class HabitStatus(PyEnum):
    DONE = 'done'
    MISSED = 'missed'

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, index=True, nullable=False)
    tz = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    habits = relationship("Habit", back_populates="user", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('tg_id', name='uq_user_tg_id'),
    )

class Habit(Base):
    __tablename__ = 'habits'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = Column(String, nullable=False)
    hour = Column(Integer, nullable=False)
    minute = Column(Integer, nullable=False)
    days_mask = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    user = relationship("User", back_populates="habits")
    logs = relationship("HabitLog", back_populates="habit", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'title', 'hour', 'minute', name='uq_habit_user_time'),
    )

class HabitLog(Base):
    __tablename__ = 'habit_logs'
    
    id = Column(Integer, primary_key=True)
    habit_id = Column(Integer, ForeignKey('habits.id', ondelete='CASCADE'), nullable=False)
    log_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(HabitStatus), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    habit = relationship("Habit", back_populates="logs")
    
    __table_args__ = (
        Index('ix_habit_logs_habit_date', 'habit_id', 'log_date'),
    )

    
def get_or_create_user(session, tg_id: int, tz: str):
    """Получить или создать пользователя"""
    user = session.query(User).filter_by(tg_id=tg_id).first()
    if not user:
        user = User(tg_id=tg_id, tz=tz)
        session.add(user)
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
    elif user.tz != tz:
        user.tz = tz
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
    return user

def exists_same(session, user_id: int, title: str, hour: int, minute: int) -> bool:
    """Проверить существование привычки с такими же параметрами"""
    return session.query(Habit).filter_by(
        user_id=user_id,
        title=title,
        hour=hour,
        minute=minute
    ).first() is not None

def add_habit(session, user_id: int, title: str, hour: int, minute: int, days_mask: int):
    """Добавить новую привычку"""
    if exists_same(session, user_id, title, hour, minute):
        raise ValueError("Привычка с таким названием и временем уже существует")
    
    habit = Habit(
        user_id=user_id,
        title=title,
        hour=hour,
        minute=minute,
        days_mask=days_mask
    )
    session.add(habit)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    return habit

def _get_utc_day_range(local_date, user_tz):
    """Преобразует локальную дату в UTC диапазон"""
    local_start = datetime.combine(local_date, time.min)
    local_end = datetime.combine(local_date, time.max)
    
    utc_start = local_start.replace(tzinfo=timezone(user_tz)).astimezone(timezone.utc)
    utc_end = local_end.replace(tzinfo=timezone(user_tz)).astimezone(timezone.utc)
    
    return utc_start, utc_end

def set_habit_done(session, habit_id: int, local_date, user_tz):
    """Отметить привычку как выполненную"""
    utc_start, utc_end = _get_utc_day_range(local_date, user_tz)
    
    log = session.query(HabitLog).filter(
        HabitLog.habit_id == habit_id,
        HabitLog.log_date >= utc_start,
        HabitLog.log_date < utc_end
    ).first()
    
    if not log:
        log = HabitLog(
            habit_id=habit_id,
            log_date=utc_start,
            status=HabitStatus.DONE
        )
        session.add(log)
    else:
        log.status = HabitStatus.DONE
    
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        raise e

def was_done_today(session, habit_id: int, local_date, user_tz):
    """Проверить, была ли привычка выполнена сегодня"""
    utc_start, utc_end = _get_utc_day_range(local_date, user_tz)
    
    return session.query(HabitLog).filter(
        HabitLog.habit_id == habit_id,
        HabitLog.log_date >= utc_start,
        HabitLog.log_date < utc_end,
        HabitLog.status == HabitStatus.DONE
    ).first() is not None

def stats_last_7_days(session, user_id: int, local_date, user_tz):
    """Получить статистику за последние 7 дней"""
    results = []
    habits = session.query(Habit).filter_by(user_id=user_id).all()
    
    for habit in habits:
        done_count = 0
        for days_ago in range(7):
            check_date = local_date - timedelta(days=days_ago)
            if was_done_today(session, habit.id, check_date, user_tz):
                done_count += 1
        
        results.append({
            'habit_id': habit.id,
            'title': habit.title,
            'done': done_count,
            'missed': 7 - done_count
        })
    
    return results

def due_habits_now(session, utc_now: datetime):
    """Получить привычки, которые должны быть выполнены сейчас"""
    due_habits = []
    
    active_habits = session.query(Habit).filter_by(is_active=True).all()
    for habit in active_habits:
        user = habit.user
        local_now = utc_now.astimezone(timezone(user.tz))
        local_weekday = local_now.weekday()
        if not (habit.days_mask >> local_weekday) & 1:
            continue
        if local_now.hour == habit.hour and local_now.minute == habit.minute:
            if not was_done_today(session, habit.id, local_now.date(), user.tz):
                due_habits.append(habit)
    return due_habits