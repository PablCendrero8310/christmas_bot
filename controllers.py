from typing import Any, Dict, List

from sqlalchemy import create_engine, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from models import Base, Gif, User, Vote


class ChristmasDB:
    def __init__(self, db_path="sqlite:///db.sqlite"):
        self.engine = create_engine(db_path, echo=False)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    # --------------------
    # USERS - CORREGIDOS
    # --------------------
    def add_user(self, telegram_id: int, username: str) -> User:
        """Añade o actualiza un usuario usando telegram_id"""
        user = self.session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            user = User(telegram_id=telegram_id, username=username)
            self.session.add(user)
        elif user.username != username:
            user_update = (
                update(User)
                .where(User.telegram_id.is_(telegram_id))
                .values(username=username)
            )
            self.session.execute(user_update)

        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
        return user

    # --------------------
    # GIFS - CORREGIDOS
    # --------------------
    def add_gif(
        self, telegram_id: int, username: str, message_id: int, file_id: str
    ) -> Gif:
        """Añade un GIF usando telegram_id del usuario"""
        # Obtener/crear usuario por telegram_id
        user = self.add_user(telegram_id, username)

        # Crear el GIF
        gif = Gif(
            message_id=message_id,
            file_id=file_id,
            user_id=user.id,  # Usar el id interno de la BD
        )

        self.session.add(gif)
        self.session.commit()
        return gif

    def has_user_submitted_gif(self, telegram_id: int) -> bool:
        """Verifica si un usuario ya ha enviado un GIF"""
        try:
            # Buscar usuario por telegram_id
            user = self.session.query(User).filter_by(telegram_id=telegram_id).first()

            if not user:
                return False

            # Verificar si tiene un GIF
            result = (
                self.session.query(Gif.id)
                # Buscar por id interno del usuario
                .filter_by(user_id=user.id).first()
            )

            return result is not None

        except Exception as e:
            print(f"Error en has_user_submitted_gif: {str(e)}")
            return False

    def get_gif(self, gif_id: int) -> Gif | None:
        return self.session.query(Gif).filter_by(id=gif_id).first()

    # --------------------
    # VOTING - CORREGIDOS
    # --------------------
    def vote_gif(self, telegram_id: int, username: str, gif_id: int) -> Vote | None:
        """Registra un voto para un GIF"""
        # Obtener/crear usuario por telegram_id
        user = self.add_user(telegram_id, username)

        # Obtener el GIF
        gif = self.get_gif(gif_id)
        if not gif:
            print(f"GIF con ID {gif_id} no encontrado")
            return None

        # ❌ No votarte a ti mismo
        if gif.user_id == user.id:  # Comparar IDs internos
            print(f"Usuario {telegram_id} intentó votar su propio GIF")
            return None

        # ❌ No votar dos veces el mismo GIF
        existing_vote = (
            self.session.query(Vote).filter_by(gif_id=gif.id, voter_id=user.id).first()
        )
        if existing_vote:
            print(f"Usuario {telegram_id} ya votó este GIF {gif_id}")
            return None

        # Crear voto
        vote = Vote(
            gif_id=gif.id,
            voter_id=user.id,  # Usar id interno
        )

        try:
            self.session.add(vote)
            self.session.commit()
            print(f"Voto registrado: usuario {telegram_id} votó GIF {gif_id}")
            return vote
        except IntegrityError as e:
            self.session.rollback()
            print(f"Error de integridad al votar: {e}")
            return None

    def get_votable_gifs(self, telegram_id: int, username: str) -> List[Gif]:
        """Obtiene GIFs que un usuario puede votar"""
        # Obtener/crear usuario por telegram_id
        user = self.add_user(telegram_id, username)

        # Subquery para GIFs ya votados por este usuario
        voted_gifs_subq = select(Vote.gif_id).where(Vote.voter_id == user.id)

        # Consulta principal
        gifs = (
            self.session.query(Gif)
            .filter(Gif.user_id != user.id)  # Excluir GIFs propios
            .filter(~Gif.id.in_(voted_gifs_subq))  # Excluir ya votados
            .all()
        )

        return gifs

    # --------------------
    # RANKING
    # --------------------
    def get_leaderboard(self, top: int = 10) -> List[Dict[str, Any]]:
        """Obtiene el ranking de GIFs más votados"""
        try:
            results = (
                self.session.query(
                    Gif.id.label("gif_id"),
                    User.username.label("username"),
                    func.count(Vote.id).label("votes"),
                    Gif.file_id.label("file_id"),
                )
                .join(User, Gif.user_id == User.id)
                .outerjoin(Vote, Vote.gif_id == Gif.id)
                .group_by(Gif.id, User.username, Gif.file_id)
                .order_by(func.count(Vote.id).desc(), Gif.id.desc())
                .limit(top)
                .all()
            )

            leaderboard = []
            for gif_id, username, votes, file_id in results:
                leaderboard.append(
                    {
                        "gif_id": gif_id,
                        "username": username or "Anónimo",
                        "votes": votes or 0,
                        "file_id": file_id,
                    }
                )

            return leaderboard

        except Exception as e:
            print(f"Error al obtener leaderboard: {str(e)}")
            return []

    # --------------------
    # UTILIDADES
    # --------------------
    def get_user_info(self, telegram_id: int) -> Dict[str, Any]:
        """Obtiene información del usuario"""
        user = self.session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return {"exists": False}

        gif = self.session.query(Gif).filter_by(user_id=user.id).first()
        votes_given = (
            self.session.query(func.count(Vote.id)).filter_by(voter_id=user.id).scalar()
            or 0
        )

        info = {
            "exists": True,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "db_id": user.id,
            "has_gif": gif is not None,
            "votes_given": votes_given,
        }

        if gif:
            votes_received = (
                self.session.query(func.count(Vote.id))
                .filter_by(gif_id=gif.id)
                .scalar()
                or 0
            )
            info.update(
                {
                    "gif_id": gif.id,
                    "file_id": gif.file_id,
                    "votes_received": votes_received,
                }
            )

        return info
