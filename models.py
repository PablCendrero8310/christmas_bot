from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# --------------------
# USERS
# --------------------


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String)

    gif = relationship("Gif", back_populates="user", cascade="all, delete-orphan")
    votes = relationship(
        "Vote", back_populates="voter_user", cascade="all, delete-orphan"
    )


# --------------------
# GIFS
# --------------------


class Gif(Base):
    __tablename__ = "gifs"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, unique=True)
    file_id = Column(String, unique=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="gif")

    votes = relationship("Vote", back_populates="gif", cascade="all, delete-orphan")


# --------------------
# VOTES
# --------------------


class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True)
    gif_id = Column(Integer, ForeignKey("gifs.id"), nullable=False)
    voter_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Un usuario solo puede votar un gif una vez
    __table_args__ = (UniqueConstraint("gif_id", "voter_id", name="unique_vote"),)

    gif = relationship("Gif", back_populates="votes")
    voter_user = relationship("User", back_populates="votes")
